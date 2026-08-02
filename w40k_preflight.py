"""W40K Translator — Pré-Voo e helpers de execução (Fase 2, sem Qt).

Toda a lógica "grátis" da jornada ① Nova Tradução vive aqui, importável
sem PySide6 (testes rodam com `python -m unittest discover -s tests`):

  - run_preflight: classificação do input (reusa funções puras do engine
    tradutor.py quando importável; fallbacks locais equivalentes)
  - cobertura de glossário e scanner de termos candidatos
  - estimativa de tokens/lotes/duração/custo (heurísticas declaradas)
  - parse de linhas de progresso do engine (tqdm + logging)
  - credenciais de API: variáveis de ambiente + cofre do Windows (keyring)
    no padrão da GUI legada — nunca persiste plaintext
  - env de subprocess no padrão comprovado da GUI antiga
  - summarize_output: contagens pós-run a partir do arquivo de saída
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import w40k_project as wp
import w40k_settings as _settings

# ─────────────────────────────────────────────────────────────────────────────
# Import opcional do engine (puro) — fallbacks mantêm o módulo utilizável
# mesmo se tradutor.py/tqdm não estiverem disponíveis.
# ─────────────────────────────────────────────────────────────────────────────

try:
    import tradutor as _engine
    _HAVE_ENGINE = True
except Exception:  # pragma: no cover - ambiente sem engine
    _engine = None
    _HAVE_ENGINE = False

try:
    import model_profiles as _profiles
    _HAVE_PROFILES = True
except Exception:  # pragma: no cover
    _profiles = None
    _HAVE_PROFILES = False

try:
    import keyring as _keyring
    _KEYRING_AVAILABLE = True
except Exception:
    _keyring = None
    _KEYRING_AVAILABLE = False


def have_engine() -> bool:
    return _HAVE_ENGINE


# Fallbacks locais equivalentes às regras do engine (nunca divergir: se o
# engine está importável, as funções dele sempre vencem).
_SKIP_TEXTS_FALLBACK = {
    "placeholder", "tbd", "todo", "n/a", "wip", "dummy", "test", "temp",
    "temporary", "stub", "none", "null", "blank", "empty", "missing",
    "notext", "no text", "new text", "string", "template", "sample text",
    "lorem ipsum", "fixme", "fix me", "deprecated", "obsolete", "removed",
    "deleted", "hidden", "unused", "reserved", "...", "[placeholder]",
    "{placeholder}", "<placeholder>", "(placeholder)",
}
_EULA_KEYWORDS_FALLBACK = (
    "eula", "end user license", "license agreement",
    "terms of service", "privacy policy", "copyright",
    "registered trademark", "all rights reserved",
)


def _should_skip(text: str) -> bool:
    if _HAVE_ENGINE:
        return _engine.should_skip(text)
    if not text or not text.strip():
        return True
    clean = re.sub(r"^[\[\{<\(]+|[\]\}>\)]+$", "", text.strip().lower())
    return clean in _SKIP_TEXTS_FALLBACK


def _is_eula(text: str) -> bool:
    if _HAVE_ENGINE:
        return _engine.is_eula(text)
    if not text:
        return False
    n = len(text)
    if n > 15000:
        return True
    if n <= 3000:
        return False
    words = text.split()
    if len(words) > 2000:
        return True
    lower = text.lower()
    return len(words) > 500 and any(kw in lower for kw in _EULA_KEYWORDS_FALLBACK)


def _estimate_tokens(text: str) -> int:
    """Heurística do engine: ~4 caracteres por token."""
    return max(1, len(text) // 4)


# ─────────────────────────────────────────────────────────────────────────────
# Resultado do Pré-Voo
# ─────────────────────────────────────────────────────────────────────────────

# Limites de comprimento idênticos aos tiers do engine (tradutor.py main).
SHORT_THRESHOLD = 50
MEDIUM_THRESHOLD = 300
LONG_THRESHOLD = 1000

# Heurística de duração: segundos assumidos por lote de API (declarada na UI).
SECONDS_PER_BATCH_EST = 15

# Cobertura de glossário considerada saudável (design §5).
COVERAGE_OK = 0.60
COVERAGE_LOW = 0.25


@dataclass
class PreflightResult:
    model: str = ""
    workers: int = 0
    total: int = 0
    skip_placeholder: int = 0
    skip_eula: int = 0
    exact_preserved: int = 0
    inline_locked: int = 0
    api_bound: int = 0
    coverage: Optional[float] = None      # fração 0..1 das api_bound com ≥1 termo
    coverage_terms: int = 0               # termos de glossário considerados
    candidates: List[Tuple[str, int]] = field(default_factory=list)
    tiers: Tuple[int, int, int, int] = (0, 0, 0, 0)  # short/med/long/xlong
    input_tokens_est: int = 0
    output_tokens_est: int = 0
    batches_est: int = 0
    duration_hint: str = ""
    cost_hint: str = ""

    @property
    def free_total(self) -> int:
        """Strings que não custam API (skips + exact EN)."""
        return self.skip_placeholder + self.skip_eula + self.exact_preserved


# ─────────────────────────────────────────────────────────────────────────────
# Cobertura de glossário + candidatos
# ─────────────────────────────────────────────────────────────────────────────

def _all_terms_pattern(glossary_path: Path, batch: int = 400):
    """Regex combinada com TODOS os termos do glossário (não só preserve)."""
    try:
        import json
        with open(glossary_path, "r", encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None, 0
    terms = [
        (t.get("term_english") or "").strip()
        for t in data.get("terms", [])
        if (t.get("term_english") or "").strip()
    ]
    if not terms:
        return None, 0
    terms.sort(key=len, reverse=True)
    parts = []
    for i in range(0, len(terms), batch):
        escaped = [re.escape(t) for t in terms[i:i + batch]]
        parts.append(r"\b(?:" + "|".join(escaped) + r")\b")
    return re.compile("|".join(parts), re.IGNORECASE), len(terms)


_CANDIDATE_RE = re.compile(
    r"\b[A-Z][a-zA-Z0-9'&\-]*(?:\s+[A-Z][a-zA-Z0-9'&\-]*){0,3}\b"
)
# Palavras capitalizadas por início de frase / discurso — ruído, não terminologia.
_CANDIDATE_STOPWORDS = {
    "the", "a", "an", "you", "your", "yours", "he", "she", "it", "its",
    "his", "her", "hers", "we", "our", "they", "their", "them", "this",
    "that", "these", "those", "if", "when", "while", "after", "before",
    "but", "and", "or", "not", "no", "yes", "in", "on", "at", "to", "of",
    "for", "with", "by", "from", "as", "is", "are", "was", "were", "be",
    "been", "do", "does", "did", "have", "has", "had", "will", "would",
    "can", "could", "shall", "should", "may", "might", "must", "i",
    "every", "each", "all", "some", "any", "many", "more", "most",
    "another", "other", "such", "what", "which", "who", "there", "here",
    # discourse / sentence openers that pass the Title Case regex a lot
    "then", "than", "thus", "hence", "however", "therefore", "whenever",
    "wherever", "whatever", "whoever", "whichever", "although", "though",
    "because", "since", "until", "unless", "while", "whereas", "meanwhile",
    "perhaps", "maybe", "please", "thank", "thanks", "well", "just", "even",
    "only", "also", "still", "already", "always", "never", "often", "once",
    "again", "further", "furthermore", "moreover", "instead", "rather",
    "enough", "quite", "very", "really", "actually", "basically",
    "look", "looks", "take", "takes", "tell", "tells", "come", "comes",
    "leave", "leaves", "make", "makes", "give", "gives", "get", "gets",
    "see", "sees", "know", "knows", "think", "thinks", "want", "wants",
    "need", "needs", "use", "uses", "try", "tries", "keep", "keeps",
    "let", "lets", "put", "puts", "set", "sets", "run", "runs",
    "where", "when", "why", "how", "who", "whom", "whose",
    "now", "today", "tomorrow", "yes", "no", "ok", "okay",
}
# Single-word Title Case that is almost never a glossary headword by itself
# (UI verbs, combat fluff, grammar). Multi-word phrases still pass.
_CANDIDATE_SINGLE_NOISE = {
    "bonus", "turn", "round", "ability", "abilities", "attack", "attacks",
    "damage", "death", "test", "tests", "influence", "master", "lord", "lady",
    "house", "human", "humanity", "please", "thank", "thanks", "well",
    "just", "even", "only", "then", "however", "whenever", "perhaps",
    "enough", "until", "once", "come", "leave", "take", "look", "tell",
    "where", "when", "domin",  # fragment of "dominated"
    "encyclopedia", "entry", "entries", "value", "values", "amount",
    "percent", "percentage", "character", "characters", "unit", "units",
    "enemy", "enemies", "ally", "allies", "target", "targets", "effect",
    "effects", "skill", "skills", "level", "levels", "type", "types",
    "area", "areas", "cell", "cells", "item", "items", "quest", "quests",
    "mission", "missions", "option", "options", "button", "buttons",
    "screen", "window", "menu", "tutorial", "continue", "cancel", "confirm",
    "accept", "decline", "close", "open", "back", "next", "previous",
    "start", "end", "begin", "finish", "complete", "completed", "failed",
    "success", "failure", "error", "warning", "note", "notes", "tip", "tips",
    "click", "hover", "select", "selected", "press", "hold", "drag",
    "right", "left", "up", "down", "north", "south", "east", "west",
    "one", "two", "three", "four", "five", "six", "seven", "eight", "nine",
    "ten", "first", "second", "third", "last", "new", "old", "good", "bad",
    "great", "small", "large", "high", "low", "full", "empty", "true", "false",
    "something", "nothing", "everything", "anything", "someone", "anyone",
    "order", "orders", "flock", "wait", "waiting", "show", "shows", "shown",
    "child", "children", "glory", "cult", "cults", "find", "finds", "found",
    "stop", "stops", "sister", "sisters", "brother", "brothers", "father",
    "mother", "friend", "friends", "people", "person", "thing", "things",
    "time", "times", "way", "ways", "part", "parts", "side", "sides",
    "place", "places", "name", "names", "word", "words", "voice", "voices",
    "power", "powers", "force", "forces", "light", "dark", "fire", "blood",
    "body", "mind", "soul", "life", "world", "worlds", "ship", "ships",
}

# Contractions / clitics: It's, I'll, Don't, You're, That's, Let's, I've…
_CONTRACTION_RE = re.compile(
    r"(?i)^(i|you|he|she|it|we|they|that|there|here|what|who|let|do|does|"
    r"did|is|are|was|were|have|has|had|will|would|can|could|should|shall|"
    r"ai|wo|ca|wouldn|shouldn|couldn|mustn|needn|mightn|oughtn|don|doesn|"
    r"didn|isn|aren|wasn|weren|haven|hasn|hadn|won|can)"
    r"('ll|'re|'ve|'d|'m|'s|n't)$"
)

# Internal Encyclopedia / UI camel ids leaked from {g|Encyclopedia:Foo}
_TECH_ID_RE = re.compile(
    r"(?i)(glossary|encyclopedia|warhammer|hitpoints|actionpoints|"
    r"movementpoints|hitsequence|damagetype|uip|tooltip)$"
)
_CAMEL_TECH_RE = re.compile(r"^[A-Z][a-z]+(?:[A-Z][a-z]+)+$")  # DamageGlossary


def _strip_markup_for_candidates(text: str) -> str:
    """Drop game/HTML markup so tag *keys* are not harvested as terms."""
    if not text:
        return ""
    # Keep human content inside paired g/d tags; drop the key path
    text = re.sub(r"\{g\|[^}]+\}", " ", text, flags=re.I)
    text = re.sub(r"\{/g\}", " ", text, flags=re.I)
    text = re.sub(r"\{d\|[^}]+\}", " ", text, flags=re.I)
    text = re.sub(r"\{/d\}", " ", text, flags=re.I)
    text = re.sub(r"\{[^}]+\}", " ", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _normalize_candidate_phrase(words: List[str]) -> Optional[str]:
    """Strip leading stopwords / trailing possessives; None if junk."""
    while words and words[0].lower().strip("'") in _CANDIDATE_STOPWORDS:
        words = words[1:]
    if not words:
        return None
    # Drop trailing 's possession for counting: "Rogue Trader's" → "Rogue Trader"
    last = words[-1]
    if last.endswith("'s") or last.endswith("'S"):
        base = last[:-2]
        if base:
            words = words[:-1] + [base]
    # Reject contractions (It's, I'll, Don't…)
    if any(_CONTRACTION_RE.match(w.replace("\u2019", "'")) for w in words):
        return None
    # Any token still a bare stopword → reject whole phrase
    cleaned = []
    for w in words:
        wl = w.lower().strip("'")
        if wl in _CANDIDATE_STOPWORDS:
            return None
        cleaned.append(w)
    if not cleaned:
        return None
    # Tech / encyclopedia internal ids
    for w in cleaned:
        if _TECH_ID_RE.search(w) or ( _CAMEL_TECH_RE.match(w) and " " not in w ):
            return None
        if w.lower() in {"encyclopedia", "testentry", "test"}:
            return None
    # Single-word noise (UI verbs, combat fluff)
    if len(cleaned) == 1 and cleaned[0].lower() in _CANDIDATE_SINGLE_NOISE:
        return None
    # Single very short tokens (Iam, Ok, …)
    if len(cleaned) == 1 and len(cleaned[0]) < 4:
        return None
    # All-caps noise of length 1-2 (UI labels OK if 3+ like MP kept? skip 1-2)
    if len(cleaned) == 1 and cleaned[0].isupper() and len(cleaned[0]) <= 2:
        return None
    phrase = " ".join(cleaned)
    if len(phrase) < 4:
        return None
    if all(w.lower() in _CANDIDATE_STOPWORDS for w in cleaned):
        return None
    return phrase


def scan_candidate_terms(texts: List[str],
                         glossary_keys: set,
                         top_n: int = 15,
                         min_count: int = 3) -> List[Tuple[str, int]]:
    """Frases EN capitalizadas (1–4 palavras) repetidas que NÃO estão no
    glossário. Retorna [(termo, ocorrências)] ordenado por frequência.

    Filtra contrações (It's/I'll), discurso (Then/However), chaves internas
    de Encyclopedia, e markup do jogo antes de escanear.
    """
    counts: Dict[str, int] = {}
    canonical: Dict[str, str] = {}
    for text in texts:
        plain = _strip_markup_for_candidates(text)
        if not plain:
            continue
        for match in _CANDIDATE_RE.finditer(plain):
            words = match.group(0).split()
            phrase = _normalize_candidate_phrase(words)
            if not phrase:
                continue
            key = phrase.lower()
            if key in glossary_keys:
                continue
            counts[key] = counts.get(key, 0) + 1
            # Prefer form without leading article leftovers already stripped
            prev = canonical.get(key)
            if prev is None or (phrase[0].isupper() and not prev[0].isupper()):
                canonical[key] = phrase
            elif prev is None:
                canonical[key] = phrase
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    return [(canonical[k], c) for k, c in ranked if c >= min_count][:top_n]


# ─────────────────────────────────────────────────────────────────────────────
# Pré-Voo principal
# ─────────────────────────────────────────────────────────────────────────────

def resolve_glossary_path(project: wp.Project,
                          repo_root: Optional[Path] = None) -> Optional[Path]:
    """Localiza o glossary.json do projeto.

    Prioridade (§9.7): o glossário DO PROJETO primeiro; o da raiz do app
    é só fallback para projetos antigos que ainda não importaram um.
    """
    rel = project.state.get("glossary") or "glossary.json"
    candidates = [project.root / rel]
    if repo_root is not None:
        candidates.append(Path(repo_root) / rel)
    for cand in candidates:
        if cand.is_file():
            return cand
    return None


def run_preflight(input_path: Path,
                  glossary_path: Optional[Path],
                  model: str = "deepseek-v4-flash",
                  top_candidates: int = 15) -> PreflightResult:
    """Análise GRÁTIS do input — nenhuma chamada de API.

    Classificação idêntica à do engine em --mode preserve:
    skip (placeholder/vazio) → EULA → exact EN → inline locked → API.
    """
    result = PreflightResult(model=model)

    data = wp.load_localization(input_path)
    strings = data["strings"]
    result.total = len(strings)

    # Glossário para classificação preserve (fonte da verdade: engine).
    glossary = None
    if glossary_path is not None:
        if _HAVE_ENGINE:
            glossary = _engine.SmartGlossary(
                str(glossary_path), "preserve",
                set(_engine.DEFAULT_PRESERVE_CATS))

    api_texts: List[str] = []
    for value in strings.values():
        text = value.get("Text", "") if isinstance(value, dict) else ""
        if _should_skip(text):
            result.skip_placeholder += 1
            continue
        if _is_eula(text):
            result.skip_eula += 1
            continue
        if glossary is not None:
            kind, _terms = glossary.classify_preserve(text)
            if kind == "exact":
                result.exact_preserved += 1
                continue
            if kind == "inline":
                result.inline_locked += 1
        api_texts.append(text)

    result.api_bound = len(api_texts)

    # ── Cobertura de glossário (todas as entradas, não só preserve) ──
    if glossary_path is not None and api_texts:
        pattern, n_terms = _all_terms_pattern(glossary_path)
        result.coverage_terms = n_terms
        if pattern is not None:
            hits = sum(1 for t in api_texts if pattern.search(t))
            result.coverage = hits / len(api_texts)

    # ── Candidatos a termo (somente leitura no P2) ──
    glossary_keys = set()
    if glossary is not None:
        glossary_keys = set(glossary.entries.keys())
    elif glossary_path is not None:
        try:
            import json
            with open(glossary_path, "r", encoding="utf-8-sig") as fh:
                gdata = json.load(fh)
            glossary_keys = {
                (t.get("term_english") or "").strip().lower()
                for t in gdata.get("terms", [])
            }
        except (OSError, ValueError):
            glossary_keys = set()
    result.candidates = scan_candidate_terms(
        api_texts, glossary_keys, top_n=top_candidates)

    # ── Estimativas (heurísticas declaradas) ──
    result.input_tokens_est = sum(_estimate_tokens(t) for t in api_texts)
    # Tradução PT tende a tamanho próximo do EN: saída ≈ entrada.
    result.output_tokens_est = result.input_tokens_est

    tiers = [0, 0, 0, 0]
    for text in api_texts:
        n = len(text)
        if n <= SHORT_THRESHOLD:
            tiers[0] += 1
        elif n <= MEDIUM_THRESHOLD:
            tiers[1] += 1
        elif n <= LONG_THRESHOLD:
            tiers[2] += 1
        else:
            tiers[3] += 1
    result.tiers = tuple(tiers)  # type: ignore
    _fill_estimate(result, model)
    return result


def _fill_estimate(result: PreflightResult, model: str) -> None:
    """Preenche campos que dependem do modelo: lotes, workers, duração,
    custo. Usado por run_preflight e recalc_estimate."""
    workers = 3
    batches_sizes = (50, 30, 12, 5)
    role = "bulk"
    label = model
    if _HAVE_PROFILES:
        _rid, prof = _settings.resolve_effective_profile(model)
        workers = int(prof.get("workers") or 3)
        batches_sizes = tuple(prof.get("batches") or batches_sizes)
        role = str(prof.get("role") or "bulk")
        label = str(prof.get("label") or model)
    result.model = model
    result.workers = workers
    result.batches_est = sum(
        -(-count // size)  # ceil
        for count, size in zip(result.tiers, batches_sizes) if count
    )
    result.duration_hint = estimate_duration_hint(result.batches_est, workers)
    result.cost_hint = (
        "custo baixo (perfil bulk/econômico)" if role == "bulk"
        else "custo premium (perfil quality)"
    ) + f" — {label}"


def recalc_estimate(result: PreflightResult, model: str) -> PreflightResult:
    """Recalcula lotes/duração/custo ao trocar de modelo, sem reclassificar
    o input (tokens e tiers não dependem do modelo)."""
    _fill_estimate(result, model)
    return result


def list_models() -> List[Tuple[str, str, str]]:
    """[(model_id, label, provider)] dos perfis EFETIVOS (código + overrides
    e adições do usuário em w40k_settings), para o picker."""
    if not _HAVE_PROFILES:
        return []
    return _settings.list_effective_models()


def provider_for_model(model: str) -> str:
    if not _HAVE_PROFILES:
        return ""
    _rid, prof = _settings.resolve_effective_profile(model)
    return str(prof.get("provider") or "")


def estimate_duration_hint(batches_est: int, workers: int) -> str:
    """Duração grosseira: lotes ÷ workers × SEGONDS_PER_BATCH_EST."""
    if batches_est <= 0:
        return "nada a traduzir"
    workers = max(1, workers)
    waves = -(-batches_est // workers)
    seconds = waves * SECONDS_PER_BATCH_EST
    if seconds < 90:
        return f"≈ {max(1, seconds // 60) or 1} min (estimativa grosseira)"
    minutes = seconds // 60
    if minutes < 90:
        return f"≈ {minutes} min (estimativa grosseira)"
    hours, rem = divmod(minutes, 60)
    return f"≈ {hours} h {rem:02d} min (estimativa grosseira)"


# ─────────────────────────────────────────────────────────────────────────────
# Parse de progresso do engine (stdout/stderr mesclados)
# ─────────────────────────────────────────────────────────────────────────────

_TQDM_RE = re.compile(r"(\d+)\s*/\s*(\d+)\s*\[")
_TQDM_ETA_RE = re.compile(r"<\s*([\d:]+)")
_PLAN_RE = re.compile(
    r"Pendentes:\s*(\d+)\s*\|\s*Exact EN:\s*(\d+)\s*\|\s*"
    r"Inline locked:\s*(\d+)\s*\|\s*Já feitos:\s*(\d+)\s*\|\s*"
    r"Pulados:\s*(\d+)")
_FINAL_RE = re.compile(
    r"Concluído:\s*(\d+)\s+traduzidos\s*\|\s*(\d+)\s+falhas\s*\|\s*"
    r"(\d+)\s+exact EN\s*\|\s*(\d+)\s+inline locked")


def parse_engine_line(line: str) -> Optional[Dict[str, Any]]:
    """Interpreta uma linha de saída do engine.

    Retorna dict com "kind":
      - "progress": {done, total, eta} — barra tqdm (12/273 [00:05<00:30])
      - "plan":     {pending, exact, inline, already_done, skipped}
      - "final":    {success, failed, exact, inline}
      - None para qualquer outra linha.
    """
    if not line:
        return None
    plan = _PLAN_RE.search(line)
    if plan:
        return {
            "kind": "plan",
            "pending": int(plan.group(1)),
            "exact": int(plan.group(2)),
            "inline": int(plan.group(3)),
            "already_done": int(plan.group(4)),
            "skipped": int(plan.group(5)),
        }
    final = _FINAL_RE.search(line)
    if final:
        return {
            "kind": "final",
            "success": int(final.group(1)),
            "failed": int(final.group(2)),
            "exact": int(final.group(3)),
            "inline": int(final.group(4)),
        }
    bar = _TQDM_RE.search(line)
    if bar:
        done, total = int(bar.group(1)), int(bar.group(2))
        eta_match = _TQDM_ETA_RE.search(line)
        return {
            "kind": "progress",
            "done": done,
            "total": total,
            "eta": eta_match.group(1) if eta_match else None,
        }
    return None


def summarize_output(output_path: Path) -> Dict[str, int]:
    """Contagens pós-run a partir do arquivo de saída do engine.

    translated = entradas sem flags de skip/preserve/falha;
    skipped_free = _preserved (exact EN) + _skipped (placeholder/eula/...);
    failed = _failed.
    """
    data = wp.load_localization(output_path)
    translated = skipped_free = failed = 0
    for entry in data["strings"].values():
        if not isinstance(entry, dict):
            continue
        if entry.get("_failed"):
            failed += 1
        elif entry.get("_preserved") or entry.get("_skipped"):
            skipped_free += 1
        else:
            translated += 1
    return {"translated": translated, "skipped_free": skipped_free,
            "failed": failed}


def summarize_resume_state(input_path: Path,
                           output_path: Optional[Path]) -> Dict[str, Any]:
    """Quanto falta para a trilha ficar completa (resume / UI Continuar).

    Compara EN de entrada com o master de saída (se existir):
      - done: UUID EN não vazio com Text PT e sem _failed
      - failed: flag _failed no master
      - missing: UUID EN não vazio ausente do master ou Text PT vazio
      - pct: 0–100 sobre strings EN não vazias

    Usado para:
      - mostrar \"Continuar de onde parou\" ao reabrir o wizard
      - NÃO marcar a trilha como done se ainda houver pending/failed
    """
    en = wp.load_localization(input_path)
    en_s = en.get("strings") or {}
    pt_s: Dict[str, Any] = {}
    if output_path is not None and Path(output_path).is_file():
        try:
            pt_s = (wp.load_localization(output_path).get("strings") or {})
        except wp.LocalizationFormatError:
            pt_s = {}

    nonempty = done = failed = missing = 0
    for key, value in en_s.items():
        if not isinstance(value, dict):
            continue
        en_text = (value.get("Text") or "").strip()
        if not en_text:
            continue
        nonempty += 1
        entry = pt_s.get(key)
        if not isinstance(entry, dict):
            missing += 1
            continue
        if entry.get("_failed"):
            failed += 1
            continue
        pt_text = (entry.get("Text") or "").strip()
        if not pt_text:
            missing += 1
            continue
        done += 1

    pending = failed + missing
    pct = round(100.0 * done / nonempty, 1) if nonempty else 100.0
    return {
        "nonempty": nonempty,
        "done": done,
        "failed": failed,
        "missing": missing,
        "pending": pending,
        "pct": pct,
        "complete": pending == 0 and nonempty > 0,
        "has_output": bool(pt_s),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Credenciais de API (padrão da GUI legada, sem fallback plaintext)
# ─────────────────────────────────────────────────────────────────────────────

KEYRING_SERVICE = "W40kTradutor"

# Mesmos nomes de chave da GUI antiga — o cofre é compartilhado.
PROVIDER_KEY_NAMES = {
    "DeepSeek": "api_key_deepseek",
    "Zhipu GLM": "api_key_zhipu",
    "Kimi (Coding)": "api_key_kimi",
    "Kimi (Moonshot)": "api_key_kimi",
    "Custom (OpenAI-compat)": "api_key_custom",
    "Custom": "api_key_custom",
}

ENV_KEY_VARS = (
    "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ZHIPU_API_KEY",
    "KIMI_API_KEY", "MOONSHOT_API_KEY",
)


def keyring_available() -> bool:
    return _KEYRING_AVAILABLE


def provider_key_name(provider: str) -> str:
    for known, key_name in PROVIDER_KEY_NAMES.items():
        if known.lower() in (provider or "").lower():
            return key_name
    return "api_key_custom"


def env_api_key() -> Optional[str]:
    """Primeira chave de API encontrada nas variáveis de ambiente."""
    for var in ENV_KEY_VARS:
        value = os.environ.get(var)
        if value:
            return value
    return None


def key_store_get(provider: str) -> str:
    """Lê a chave do cofre do Windows (keyring). "" se indisponível."""
    if not _KEYRING_AVAILABLE:
        return ""
    try:
        return _keyring.get_password(
            KEYRING_SERVICE, provider_key_name(provider)) or ""
    except Exception:
        return ""


def key_store_set(provider: str, value: str) -> bool:
    """Grava a chave no cofre do Windows. False se o cofre não existe —
    nesse caso a chave NÃO é persistida em lugar nenhum (sem plaintext)."""
    ok, _detail = key_store_set_ex(provider, value)
    return ok


def key_store_delete(provider: str) -> bool:
    """Remove a chave do cofre do Windows. False se indisponível/ausente."""
    if not _KEYRING_AVAILABLE:
        return False
    try:
        _keyring.delete_password(
            KEYRING_SERVICE, provider_key_name(provider))
        return True
    except Exception:
        return False


def key_store_set_ex(provider: str, value: str) -> Tuple[bool, str]:
    """key_store_set com diagnóstico: (ok, detalhe PT-BR para a UI).

    Distingue "keyring não instalado" de "backend do cofre falhou" — o
    chamador deve avisar o usuário visivelmente quando ok=False, em vez
    de deixar a gravação falhar em silêncio.
    """
    if not value:
        return False, "nenhuma chave informada"
    if not _KEYRING_AVAILABLE:
        return False, ("pacote 'keyring' não instalado neste Python — "
                       "instale com: py -3 -m pip install keyring")
    try:
        _keyring.set_password(KEYRING_SERVICE, provider_key_name(provider),
                              value)
        return True, "chave salva no cofre do Windows"
    except Exception as exc:
        return False, f"falha ao gravar no cofre do Windows: {exc}"


def resolve_api_key(provider: str, typed: str = "") -> Tuple[str, str]:
    """Resolve a chave na ordem: campo digitado → ambiente → cofre.

    Retorna (chave, origem) — origem em PT-BR para a UI.
    """
    if typed.strip():
        return typed.strip(), "digitada agora"
    env = env_api_key()
    if env:
        return env, "variável de ambiente"
    saved = key_store_get(provider)
    if saved:
        return saved, "cofre do Windows"
    return "", ""


def resolve_any_api_key(preferred_provider: str = "",
                        typed: str = "") -> Tuple[str, str, str]:
    """Resolve chave para um provedor preferido, com fallback amplo.

    Ordem:
      1) texto digitado (origem = preferred ou \"\")
      2) chave do preferred_provider (env genérico + cofre desse provedor)
      3) qualquer variável de ambiente conhecida
      4) cofre de cada provedor conhecido (DeepSeek, Zhipu, Kimi, Custom…)

    Retorna (chave, origem_pt, provider_que_bateu).
    Usado por fluxos fora da jornada de tradução (ex.: Sugerir via LLM no
    glossário), onde não há campo de chave na tela e o modelo padrão pode
    ser DeepSeek enquanto a única chave salva é Zhipu/ZAI.
    """
    if typed.strip():
        return typed.strip(), "digitada agora", (preferred_provider or "")

    if preferred_provider:
        key, src = resolve_api_key(preferred_provider, "")
        if key:
            # env_api_key is global — attribute to preferred when it hits
            return key, src, preferred_provider

    env = env_api_key()
    if env:
        return env, "variável de ambiente", (preferred_provider or "")

    # Walk known keyring slots (and any provider name we know)
    tried = set()
    for prov in list(PROVIDER_KEY_NAMES.keys()):
        if prov in tried:
            continue
        tried.add(prov)
        saved = key_store_get(prov)
        if saved:
            return saved, f"cofre do Windows ({prov})", prov
    return "", "", ""


def subprocess_env(model: str, key: str,
                   base_url: str = "") -> Dict[str, str]:
    """Env para o subprocess tradutor.py — padrão comprovado da GUI antiga
    (GUI legada, removida na v2.0): injeta a chave em todas as variáveis
    conhecidas e a base URL do modelo em DEEPSEEK_BASE_URL."""
    env = os.environ.copy()
    if key:
        for var in ("DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ZHIPU_API_KEY",
                    "KIMI_API_KEY", "MOONSHOT_API_KEY"):
            env[var] = key
    if not base_url and _HAVE_PROFILES:
        _rid, prof = _settings.resolve_effective_profile(model)
        base_url = str(prof.get("url") or "")
    if not base_url:
        base_url = "https://api.deepseek.com"
    env["DEEPSEEK_BASE_URL"] = base_url
    return env


# ─────────────────────────────────────────────────────────────────────────────
# Teste de conexão (urllib puro — usado pela aba Provedores das Configurações)
# ─────────────────────────────────────────────────────────────────────────────

def _http_error_detail(exc) -> str:
    """Extrai status + mensagem do servidor de um HTTPError (PT-BR)."""
    detail = ""
    try:
        body = exc.read().decode("utf-8", errors="replace")
        import json as _json
        parsed = _json.loads(body)
        if isinstance(parsed, dict):
            err = parsed.get("error")
            if isinstance(err, dict):
                detail = str(err.get("message") or "")
            elif err:
                detail = str(err)
            if not detail:
                detail = str(parsed.get("message") or parsed.get("msg") or "")
    except Exception:
        detail = ""
    if len(detail) > 200:
        detail = detail[:200] + "…"
    hint = " — verifique a chave de API" if exc.code in (401, 403) else ""
    suffix = f": {detail}" if detail else ""
    return f"HTTP {exc.code}{hint}{suffix}"


def test_connection(base_url: str, api_key: str = "",
                    model: str = "", timeout: float = 8.0
                    ) -> Tuple[bool, str]:
    """Testa o provedor de forma robusta (stdlib urllib, sem deps):

    1) GET {base_url}/models com Authorization: Bearer (quando há chave);
    2) se /models falhar, fallback para um probe mínimo de chat completions
       (1 token, `model`) — provedores como o endpoint coding da Zhipu não
       expõem /models mas respondem chat normalmente.

    Retorna (ok, mensagem PT-BR com status HTTP exato + mensagem do servidor).
    """
    import socket
    import urllib.error
    import urllib.request

    base = (base_url or "").strip().rstrip("/")
    if not base:
        return False, "Informe uma base URL primeiro."

    def _req(url: str, method: str = "GET", payload: Optional[bytes] = None):
        headers = {"Accept": "application/json"}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"
        if payload is not None:
            headers["Content-Type"] = "application/json"
        return urllib.request.Request(url, data=payload, headers=headers,
                                      method=method)

    # 1) GET /models
    models_err = ""
    try:
        with urllib.request.urlopen(_req(f"{base}/models"),
                                    timeout=timeout) as resp:
            return True, f"✔ Conexão OK — GET /models respondeu HTTP {resp.status}."
    except urllib.error.HTTPError as exc:
        models_err = _http_error_detail(exc)
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        models_err = f"falha de conexão ({exc})"

    # 2) Fallback: probe mínimo de chat completions
    import json as _json
    probe = {
        "model": model or "ping",
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 1,
    }
    try:
        with urllib.request.urlopen(
                _req(f"{base}/chat/completions", method="POST",
                     payload=_json.dumps(probe).encode("utf-8")),
                timeout=timeout) as resp:
            return True, (f"✔ Conexão OK — /models falhou ({models_err}), "
                          f"mas chat completions respondeu HTTP {resp.status}.")
    except urllib.error.HTTPError as exc:
        return False, (f"✖ /models: {models_err} · "
                       f"chat completions: {_http_error_detail(exc)}")
    except (urllib.error.URLError, socket.timeout, OSError) as exc:
        return False, f"✖ Falha de conexão: {exc}"


# ─────────────────────────────────────────────────────────────────────────────
# Pre-Scan cache (reuso pelo engine via --prescan-cache; padrão da GUI antiga)
# ─────────────────────────────────────────────────────────────────────────────

def write_prescan_cache(input_path: Path, glossary_path: Optional[Path],
                        out_path: Path, mode: str = "preserve"
                        ) -> Dict[str, int]:
    """Grava prescan_cache.json no formato que tradutor.py --prescan-cache
    entende: buckets de UUIDs PRESERVED (exact EN) / SKIP (placeholder) /
    EULA + source_hash (md5 do input) + preserve_mode.

    A classificação é idêntica à do engine (reusa as funções dele quando
    importável). Retorna contagens por bucket.
    """
    import hashlib
    import json as _json

    data = wp.load_localization(input_path)
    strings = data["strings"]

    glossary = None
    if glossary_path is not None and _HAVE_ENGINE:
        glossary = _engine.SmartGlossary(
            str(glossary_path), mode, set(_engine.DEFAULT_PRESERVE_CATS))

    preserved: List[str] = []
    skip: List[str] = []
    eula: List[str] = []
    for key, value in strings.items():
        text = value.get("Text", "") if isinstance(value, dict) else ""
        if _should_skip(text):
            skip.append(key)
            continue
        if _is_eula(text):
            eula.append(key)
            continue
        if glossary is not None:
            kind, _terms = glossary.classify_preserve(text)
            if kind == "exact":
                preserved.append(key)
                continue

    src_hash = hashlib.md5(Path(input_path).read_bytes()).hexdigest()
    cache = {
        "source_hash": src_hash,
        "preserve_mode": mode,
        "buckets": {"PRESERVED": preserved, "SKIP": skip, "EULA": eula},
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_name(out_path.name + ".tmp")
    tmp.write_text(_json.dumps(cache, ensure_ascii=False), encoding="utf-8")
    tmp.replace(out_path)
    return {"PRESERVED": len(preserved), "SKIP": len(skip),
            "EULA": len(eula)}
