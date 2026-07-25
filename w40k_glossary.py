"""W40K Translator — Espaço Glossário (jornada ⑤, §4.5 do GUI_REDESIGN, sem Qt).

Toda a lógica do diálogo ⑤ Glossário vive aqui, testável com stdlib puro:

  - load/save do glossário DO PROJETO (escrita atômica + backup em backups/)
  - busca/filtro (texto + categoria + preserve/inline) e validação de termos
  - auto-build: scan de candidatos (reuso de w40k_preflight) com contexto
    de amostra, defaults de categoria/preserve, merge com dedupe
  - sugestão PT via LLM em UMA chamada em lote (prompt builder + parser
    robusto a desvios de formato/numeração, no padrão do engine)
  - semente wiki: offline (wiki_sync.get_wiki_data) e ao vivo (MediaWiki
    API, lógica portada da GUI antiga tradutor_desktop.py ~2722-2794)

O glossário editado é SEMPRE o do projeto (§9.7) — nunca o do repo.
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import w40k_preflight as pf
import w40k_project as wp

# Campos do schema real das entradas (verificado contra glossary.json).
ENTRY_FIELDS = (
    "term_english", "term_translated", "category", "preserve", "inline",
    "source", "context", "confidence", "usage_count", "created_at",
)
CONFIDENCES = ("low", "medium", "high")
DEFAULT_CATEGORY = "mod"

SOURCE_AUTO_BUILD = "auto_build"
SOURCE_AUTO_BUILD_LLM = "auto_build_llm"
SOURCE_MANUAL = "manual"
SOURCE_WIKI_SEED = "wh40k_wiki"
SOURCE_WIKI_LIVE = "live_wiki"


# ─────────────────────────────────────────────────────────────────────────────
# Load / save / backup
# ─────────────────────────────────────────────────────────────────────────────

def load_glossary(path: Path) -> Dict[str, Any]:
    """Lê o glossário (tolerante: ausente/malformado → estrutura vazia)."""
    try:
        with open(path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError, UnicodeDecodeError):
        return {"metadata": {}, "terms": []}
    if not isinstance(data, dict):
        return {"metadata": {}, "terms": []}
    if not isinstance(data.get("terms"), list):
        data["terms"] = []
    if not isinstance(data.get("metadata"), dict):
        data["metadata"] = {}
    return data


def _touch_metadata(data: Dict[str, Any]) -> None:
    meta = data.setdefault("metadata", {})
    meta["updated_at"] = datetime.now().isoformat()
    meta["total_terms"] = len(data.get("terms", []))


def atomic_write_glossary(path: Path, data: Dict[str, Any]) -> None:
    """Escrita atômica (tmp → replace) já carimbando a metadata."""
    _touch_metadata(data)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
    tmp.replace(path)


def backup_glossary(project: wp.Project) -> Optional[Path]:
    """Cópia de segurança do glossário do projeto em backups/ (padrão das
    outras jornadas). None se o glossário ainda não existe."""
    src = project.glossary_path()
    if not src.is_file():
        return None
    import shutil
    backups = project.root / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    dest = backups / f"glossary_pre-edit_{stamp}.json"
    shutil.copy2(src, dest)
    return dest


def save_project_glossary(project: wp.Project, data: Dict[str, Any]
                          ) -> Dict[str, Any]:
    """Grava o glossário do projeto (atômico) e atualiza o glossary_stamp
    no project.json — o card GLOSSÁRIO do dashboard reflete na hora."""
    atomic_write_glossary(project.glossary_path(), data)
    meta = data.get("metadata", {})
    stamp = {
        "terms": len(data.get("terms", [])),
        "built_for": meta.get("game") or wp.GAME_PROFILE,
        "name": meta.get("name") or "Glossário do projeto",
        "kind": meta.get("kind") or wp.GLOSSARY_KIND_BASE,
        "mod_name": meta.get("mod_name"),
        "parent": meta.get("parent"),
    }
    project.state["glossary"] = "glossary.json"
    project.state["glossary_stamp"] = stamp
    project.save()
    return stamp


# ─────────────────────────────────────────────────────────────────────────────
# Termos: validação, CRUD, filtro
# ─────────────────────────────────────────────────────────────────────────────

def normalize_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
    """Completa defaults e mantém só os campos do schema."""
    en = str(entry.get("term_english") or "").strip()
    pt = str(entry.get("term_translated") or "").strip() or en
    confidence = str(entry.get("confidence") or "medium").strip().lower()
    if confidence not in CONFIDENCES:
        confidence = "medium"
    try:
        usage = int(entry.get("usage_count") or 0)
    except (TypeError, ValueError):
        usage = 0
    return {
        "term_english": en,
        "term_translated": pt,
        "category": str(entry.get("category") or DEFAULT_CATEGORY).strip()
                    or DEFAULT_CATEGORY,
        "preserve": bool(entry.get("preserve", True)),
        "inline": bool(entry.get("inline", False)),
        "source": str(entry.get("source") or SOURCE_MANUAL),
        "context": str(entry.get("context") or ""),
        "confidence": confidence,
        "usage_count": usage,
        "created_at": str(entry.get("created_at")
                          or datetime.now().isoformat()),
    }


def validate_entry(entry: Dict[str, Any]) -> List[str]:
    """Lista de erros (vazia = válido). Mensagens PT-BR para a UI."""
    errors = []
    if not str(entry.get("term_english") or "").strip():
        errors.append("O termo em inglês é obrigatório.")
    if len(str(entry.get("term_english") or "").strip()) > 200:
        errors.append("Termo em inglês longo demais (máx. 200 caracteres).")
    conf = str(entry.get("confidence") or "medium").strip().lower()
    if conf not in CONFIDENCES:
        errors.append(f"Confiança inválida: {conf} "
                      f"(use {'/'.join(CONFIDENCES)}).")
    return errors


def find_term(terms: List[Dict[str, Any]], term_english: str) -> int:
    """Índice do termo (case-insensitive) ou -1."""
    key = (term_english or "").strip().lower()
    for i, t in enumerate(terms):
        if str(t.get("term_english") or "").strip().lower() == key:
            return i
    return -1


def add_term(data: Dict[str, Any], entry: Dict[str, Any]) -> Dict[str, Any]:
    errors = validate_entry(entry)
    if errors:
        raise ValueError(" ".join(errors))
    terms = data.setdefault("terms", [])
    if find_term(terms, entry["term_english"]) >= 0:
        raise ValueError(f"“{entry['term_english']}” já existe no glossário.")
    normalized = normalize_entry(entry)
    terms.append(normalized)
    return normalized


def update_term(data: Dict[str, Any], original_en: str,
                entry: Dict[str, Any]) -> Dict[str, Any]:
    errors = validate_entry(entry)
    if errors:
        raise ValueError(" ".join(errors))
    terms = data.setdefault("terms", [])
    idx = find_term(terms, original_en)
    if idx < 0:
        raise ValueError(f"“{original_en}” não existe no glossário.")
    if entry["term_english"].strip().lower() != original_en.strip().lower():
        if find_term(terms, entry["term_english"]) >= 0:
            raise ValueError(
                f"“{entry['term_english']}” já existe no glossário.")
    normalized = normalize_entry(entry)
    # Preserva created_at/usage_count originais na edição.
    old = terms[idx]
    normalized["created_at"] = old.get("created_at") or normalized["created_at"]
    normalized["usage_count"] = int(old.get("usage_count") or 0)
    terms[idx] = normalized
    return normalized


def remove_term(data: Dict[str, Any], term_english: str) -> bool:
    terms = data.setdefault("terms", [])
    idx = find_term(terms, term_english)
    if idx < 0:
        return False
    terms.pop(idx)
    return True


def categories_of(terms: List[Dict[str, Any]]) -> List[str]:
    return sorted({str(t.get("category") or "").strip()
                   for t in terms if str(t.get("category") or "").strip()})


def filter_terms(terms: List[Dict[str, Any]], query: str = "",
                 category: str = "",
                 preserve: Optional[bool] = None,
                 inline: Optional[bool] = None) -> List[Dict[str, Any]]:
    """Filtro da aba Termos: texto (EN/PT/contexto, case-insensitive) +
    categoria exata + flags preserve/inline (None = tanto faz)."""
    q = (query or "").strip().lower()
    cat = (category or "").strip()
    out = []
    for t in terms:
        if cat and str(t.get("category") or "") != cat:
            continue
        if preserve is not None and bool(t.get("preserve")) != preserve:
            continue
        if inline is not None and bool(t.get("inline")) != inline:
            continue
        if q:
            hay = " ".join([
                str(t.get("term_english") or ""),
                str(t.get("term_translated") or ""),
                str(t.get("context") or ""),
            ]).lower()
            if q not in hay:
                continue
        out.append(t)
    return out


# ─────────────────────────────────────────────────────────────────────────────
# Auto-build: candidatos → aprovação → sugestão PT → merge
# ─────────────────────────────────────────────────────────────────────────────

def guess_category(term: str, existing_terms: List[Dict[str, Any]]) -> str:
    """Palpite de categoria por vocabulário compartilhado, em dois níveis:
    1) o candidato contém um termo existente (ou vice-versa) — herda a
       categoria do mais específico;
    2) compartilham uma PALAVRA significativa (≥4 letras, fora stopwords)
       — herda a categoria do termo com mais palavras em comum.
    Senão, 'mod'. Heurística simples e visível na UI."""
    key = (term or "").strip().lower()
    if not key:
        return DEFAULT_CATEGORY

    # Nível 1: substring (mais forte)
    best_cat = ""
    best_overlap = 0
    for t in existing_terms:
        en = str(t.get("term_english") or "").strip().lower()
        if len(en) < 4:
            continue
        overlap = 0
        if en in key:
            overlap = len(en)
        elif key in en and len(key) >= 4:
            overlap = len(key)
        if overlap > best_overlap:
            best_overlap = overlap
            best_cat = str(t.get("category") or "")
    if best_cat:
        return best_cat

    # Nível 2: palavras significativas em comum
    cand_words = {w for w in re.split(r"[^a-z0-9]+", key)
                  if len(w) >= 4 and w not in pf._CANDIDATE_STOPWORDS}
    if not cand_words:
        return DEFAULT_CATEGORY
    best_cat = ""
    best_shared = 0
    for t in existing_terms:
        en = str(t.get("term_english") or "").strip().lower()
        en_words = {w for w in re.split(r"[^a-z0-9]+", en)
                    if len(w) >= 4 and w not in pf._CANDIDATE_STOPWORDS}
        shared = len(cand_words & en_words)
        if shared > best_shared:
            best_shared = shared
            best_cat = str(t.get("category") or "")
    return best_cat or DEFAULT_CATEGORY


def default_preserve(term: str) -> bool:
    """Candidatos do scanner são nomes próprios capitalizados por
    construção — preserve ON por padrão (o usuário desmarca se quiser)."""
    return True


def _sample_context(texts: List[str], term: str, width: int = 70) -> str:
    """Primeira ocorrência do termo nos textos, com ~width chars ao redor."""
    needle = (term or "").lower()
    if not needle:
        return ""
    for text in texts:
        idx = text.lower().find(needle)
        if idx < 0:
            continue
        start = max(0, idx - width // 2)
        end = min(len(text), idx + len(term) + width // 2)
        snippet = text[start:end].replace("\n", " ").strip()
        if start > 0:
            snippet = "…" + snippet
        if end < len(text):
            snippet += "…"
        return snippet
    return ""


def scan_project_candidates(project: wp.Project, glossary_path: Path,
                            top_n: int = 100, min_count: int = 3
                            ) -> List[Dict[str, Any]]:
    """Scanner da aba Construir: input do projeto → linhas rankeadas
    {term, count, context, pt, category, preserve, inline, approved}.

    Reusa o scanner do Pre-Flight (w40k_preflight) sobre os textos
    API-bound (pulando placeholder/EULA com as mesmas regras do engine).
    """
    input_path = project.input_path()
    if input_path is None:
        raise wp.ProjectError("O projeto não tem input registrado.")
    data = wp.load_localization(input_path)
    texts = []
    for value in data["strings"].values():
        text = value.get("Text", "") if isinstance(value, dict) else ""
        if pf._should_skip(text) or pf._is_eula(text):
            continue
        texts.append(text)

    gdata = load_glossary(glossary_path)
    glossary_keys = {
        str(t.get("term_english") or "").strip().lower()
        for t in gdata["terms"]
    }
    ranked = pf.scan_candidate_terms(texts, glossary_keys,
                                     top_n=top_n, min_count=min_count)
    rows = []
    for term, count in ranked:
        rows.append({
            "term": term,
            "count": count,
            "context": _sample_context(texts, term),
            "pt": "",
            "category": guess_category(term, gdata["terms"]),
            "preserve": default_preserve(term),
            "inline": False,
            "approved": True,
            "source": SOURCE_AUTO_BUILD,
        })
    return rows


def merge_terms(data: Dict[str, Any], entries: List[Dict[str, Any]]
                ) -> Tuple[int, int]:
    """Mescla entradas no glossário. Dedupe por term_english
    case-insensitive. Retorna (adicionados, pulados)."""
    terms = data.setdefault("terms", [])
    added = skipped = 0
    for entry in entries:
        en = str(entry.get("term_english") or "").strip()
        if not en or find_term(terms, en) >= 0:
            skipped += 1
            continue
        terms.append(normalize_entry(entry))
        added += 1
    if added:
        _touch_metadata(data)
    return added, skipped


def entries_from_candidate_rows(rows: List[Dict[str, Any]]
                                ) -> List[Dict[str, Any]]:
    """Linhas aprovadas + com PT preenchido → entradas prontas p/ merge.
    PT vazio cai para o EN (padrão preserve). Confiança: low se a PT veio
    do LLM (revisão humana pendente), medium se digitada."""
    entries = []
    for row in rows:
        if not row.get("approved"):
            continue
        en = str(row.get("term") or "").strip()
        if not en:
            continue
        pt = str(row.get("pt") or "").strip()
        from_llm = row.get("source") == SOURCE_AUTO_BUILD_LLM and bool(pt)
        entries.append({
            "term_english": en,
            "term_translated": pt or en,
            "category": str(row.get("category") or DEFAULT_CATEGORY),
            "preserve": bool(row.get("preserve", True)),
            "inline": bool(row.get("inline", False)),
            "source": row.get("source") or SOURCE_AUTO_BUILD,
            "context": str(row.get("context") or "")[:200],
            "confidence": "low" if from_llm else "medium",
            "usage_count": int(row.get("count") or 1),
        })
    return entries


# ─────────────────────────────────────────────────────────────────────────────
# Sugestão PT via LLM — UMA chamada em lote
# ─────────────────────────────────────────────────────────────────────────────

def build_llm_prompt(terms: List[str]) -> Tuple[str, str]:
    """(system, user) para traduzir os termos EN → PT-BR em lote.

    Formato pedido: JSON array [{"en": "...", "pt": "..."}] — o parser
    tolera desvios (numeração, fences, dict em vez de lista).
    """
    system = (
        "You are a translator for Warhammer 40,000: Rogue Trader (Owlcat "
        "CRPG). Translate each English game term into natural Brazilian "
        "Portuguese, keeping the tone of the setting. Proper nouns that "
        "the community usually keeps in English may stay in English. "
        "Return ONLY a JSON array of objects with exactly the keys "
        '"en" and "pt", one per input term, same order. No explanations.'
    )
    numbered = "\n".join(f"{i + 1}. {t}" for i, t in enumerate(terms))
    user = (
        "Translate these terms to PT-BR and answer with the JSON array "
        "([{\"en\": \"...\", \"pt\": \"...\"}]):\n\n" + numbered
    )
    return system, user


def parse_llm_suggestions(content: str, expected_terms: List[str]
                          ) -> Dict[str, str]:
    """Extrai {termo_en: pt} da resposta do LLM. Robusto a:
    fences ```json, dict em vez de lista, chaves numeradas ("1. Term"),
    drift de caixa — e ignora termos fora da lista esperada."""
    if not content:
        return {}
    text = content.strip()
    text = text.removeprefix("```json").removeprefix("```")
    text = text.removesuffix("```").strip()

    def _clean_key(k: str) -> str:
        k = re.sub(r"^\s*\d+[\.\)\-:]\s*", "", str(k))  # "1. Term" → "Term"
        return k.strip().strip('"').strip()

    pairs: Dict[str, str] = {}
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            # {"Term": "Trad"} ou {"translations": [...]}
            for v in parsed.values():
                if isinstance(v, list):
                    parsed = v
                    break
            else:
                for k, v in parsed.items():
                    if isinstance(v, str):
                        pairs[_clean_key(k)] = v.strip()
                parsed = None
        if isinstance(parsed, list):
            for item in parsed:
                if isinstance(item, dict):
                    en = item.get("en") or item.get("term_english") or ""
                    pt = item.get("pt") or item.get("term_translated") or ""
                    if en and pt:
                        pairs[_clean_key(en)] = str(pt).strip()
                elif isinstance(item, str) and "—" in item:
                    en, pt = item.split("—", 1)
                    pairs[_clean_key(en)] = pt.strip()
    except ValueError:
        # Fallback linha a linha: "Term = Trad" | "Term — Trad" | "1. Term: Trad"
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            for sep in ("—", "=", ":"):
                if sep in line:
                    en, pt = line.split(sep, 1)
                    en, pt = _clean_key(en), pt.strip()
                    if en and pt:
                        pairs[en] = pt
                    break

    canonical = {t.strip().lower(): t for t in expected_terms}
    out: Dict[str, str] = {}
    for en, pt in pairs.items():
        real = canonical.get(en.strip().lower())
        if real and pt:
            out[real] = pt
    return out


def suggest_translations_llm(terms: List[str], model: str, api_key: str,
                             base_url: str,
                             opener: Optional[Callable] = None
                             ) -> Dict[str, str]:
    """UMA chamada chat/completions traduzindo os termos em lote.
    `opener` injetável para testes (default: urllib.request.urlopen)."""
    import urllib.request

    if not terms:
        return {}
    if not api_key:
        raise ValueError("Nenhuma chave de API disponível — configure em "
                         "⚙ Configurações.")
    system, user = build_llm_prompt(terms)
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": user}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }).encode("utf-8")
    req = urllib.request.Request(
        base_url.rstrip("/") + "/chat/completions",
        data=payload, method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {api_key}"})
    open_fn = opener or urllib.request.urlopen
    with open_fn(req, timeout=60) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    content = body["choices"][0]["message"]["content"] or ""
    return parse_llm_suggestions(content, terms)


# ─────────────────────────────────────────────────────────────────────────────
# Semente wiki — offline (wiki_sync) e ao vivo (MediaWiki API)
# ─────────────────────────────────────────────────────────────────────────────

def wiki_seed_entries(only_cats: Optional[List[str]] = None
                      ) -> List[Dict[str, Any]]:
    """Entradas da semente OFFLINE (data/glossaries/wiki_terms.json via
    wiki_sync.get_wiki_data — módulo intocado, só importado)."""
    import wiki_sync
    wiki = wiki_sync.get_wiki_data()
    entries = []
    for category, names in wiki.items():
        if only_cats and category not in only_cats:
            continue
        for name in names:
            entries.append({
                "term_english": str(name),
                "term_translated": str(name),
                "category": category,
                "preserve": True,
                "inline": False,
                "source": SOURCE_WIKI_SEED,
                "context": f"WH40K Wiki — {category}",
                "confidence": "high",
                "usage_count": 1,
            })
    return entries


_WIKI_API = "https://roguetrader.wh40k.wiki/api.php"
_WIKI_UA = {"User-Agent": "W40kTradutor/1.0 (fan translation tool; "
                          "github.com/ltsuemitsu/w40k-tradutor)"}
_WIKI_CAT_MAP = {
    "weapon": "weapon", "talent": "talent", "ability": "ability",
    "skill": "skill", "homeworld": "homeworld", "archetype": "archetype",
    "armour": "armour", "consumable": "consumable",
}


def wiki_fetch_live(term: str, opener: Optional[Callable] = None
                    ) -> Dict[str, Any]:
    """Busca UM termo na wiki ao vivo (MediaWiki API) — lógica portada da
    GUI antiga (tradutor_desktop._live_wiki_scrape_dialog ~2722-2794).
    Retorna uma entrada pronta para merge; levanta ValueError se não achar."""
    import urllib.parse
    import urllib.request

    term = (term or "").strip()
    if not term:
        raise ValueError("Informe o termo para buscar na wiki.")
    open_fn = opener or urllib.request.urlopen

    def wiki_api(params: Dict[str, str]) -> Dict[str, Any]:
        url = _WIKI_API + "?" + urllib.parse.urlencode(
            dict(params, format="json"))
        req = urllib.request.Request(url, headers=_WIKI_UA)
        with open_fn(req, timeout=15) as resp:
            return json.loads(resp.read().decode("utf-8"))

    # 1) melhor página para o termo
    s = wiki_api({"action": "query", "list": "search",
                  "srsearch": term, "srlimit": "1"})
    hits = s.get("query", {}).get("search", [])
    if not hits:
        raise ValueError(f"Nenhuma página da wiki para “{term}”.")
    title = hits[0]["title"]

    # 2) wikitext da página (seguindo redirects)
    w = wiki_api({"action": "query", "prop": "revisions",
                  "rvprop": "content", "rvslots": "main",
                  "titles": title, "redirects": "1"})
    page = next(iter(w.get("query", {}).get("pages", {}).values()))
    if "missing" in page or "revisions" not in page:
        raise ValueError(f"Página “{title}” sem conteúdo na wiki.")
    resolved = page.get("title", title)
    wikitext = page["revisions"][0]["slots"]["main"]["*"]

    # 3) parse leve: nome do template do infobox + campos descritivos
    m = re.search(r"\{\{\s*([A-Za-z][A-Za-z0-9 _-]*)", wikitext)
    template = m.group(1).strip() if m else ""
    fields = dict(re.findall(r"\n\|([A-Za-z0-9_]+)=([^\n|]*)", wikitext))
    interesting = [f"{k}={fields[k].strip()}" for k in
                   ("type", "family", "category", "rarity", "cargo_type")
                   if fields.get(k) and fields[k].strip()]
    page_url = ("https://roguetrader.wh40k.wiki/wiki/"
                + urllib.parse.quote(resolved.replace(" ", "_")))

    category = _WIKI_CAT_MAP.get(template.lower(), "wiki_live")
    context = f"WH40K Wiki — {template or 'page'}"
    if interesting:
        context += ": " + ", ".join(interesting[:4])
    context += f" ({page_url})"

    return {
        "term_english": resolved,
        "term_translated": resolved,
        "category": category,
        "preserve": True,
        "inline": False,
        "source": SOURCE_WIKI_LIVE,
        "context": context,
        "confidence": "medium",
        "usage_count": 1,
    }
