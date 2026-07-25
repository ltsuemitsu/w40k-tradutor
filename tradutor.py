#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Tradutor JSON de Jogos — Arquitetura v3.0
===========================================

Ferramenta ÚNICA de tradução. Tudo o que não é tradução está em outro script.

Cenários:
  1. Primeira tradução: tradutor.py -i en.json -o pt.json --glossary g.json --resume
  2. Só o novo:        tradutor.py -i apenas_novos.json -o fix.json --glossary g.json
  3. Com categorias:   tradutor.py -i en.json -o pt.json --glossary g.json --categories cats.json

Modos de Preservação:
  --mode complete     → Traduz tudo (100% português)
  --mode preserve     → Preserva termos do glossário marcados como "preservar"
  --preserve-cats     → Quais categorias preservar (default: ver DEFAULT_PRESERVE_CATS)

Uso:
    # Primeira vez — do zero
    python tradutor.py -i enGB.json -o ptBR.json --glossary glossary.json --resume

    # Preservando mecânicas (nomes de armas, skills, etc. ficam em inglês)
    python tradutor.py -i enGB.json -o ptBR.json --glossary glossary.json --mode preserve --resume

    # Escolhendo o que preservar
    python tradutor.py -i enGB.json -o ptBR.json --glossary glossary.json \\
        --mode preserve --preserve-cats weapon,talent,skill

    # Traduzindo apenas arquivo de diffs
    python tradutor.py -i retraduzir.json -o fix.json --glossary glossary.json --extract-every 0

    # Continuar após erro
    python tradutor.py -i enGB.json -o ptBR.json --glossary glossary.json --resume
"""

import json
import os
import re
import sys
import time
import argparse
import hashlib
import logging
import tempfile
import shutil
import concurrent.futures
import threading
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, List, Tuple, Any, Set
from datetime import datetime
from collections import defaultdict
from tqdm import tqdm

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', datefmt='%H:%M:%S')
logger = logging.getLogger("Tradutor")

# ─── CONSTANTES ───
DEFAULT_BATCH_SIZE = 10
DEFAULT_MAX_WORKERS = 3
DEFAULT_MAX_RETRIES = 3
DEFAULT_MAX_FAILURES = 3
DEFAULT_TEMPERATURE = 0.15
DEFAULT_TARGET_LANGUAGE = "Português do Brasil"
MAX_TOKENS_PER_BATCH = 12500

# Single source of truth for --mode preserve category filter (GUI + CLI).
# Matches wiki_sync categories + attribute/lore/skill used by the game glossary.
DEFAULT_PRESERVE_CATS = (
    "weapon", "talent", "skill", "ability", "attribute", "lore",
    "armour", "helmet", "consumable", "necklace", "gloves", "cloak", "boots",
    "pet_protocol", "conviction", "archetype", "homeworld", "origin", "accessory",
)
DEFAULT_PRESERVE_CATS_CSV = ",".join(DEFAULT_PRESERVE_CATS)

SKIP_TEXTS = {"placeholder","tbd","todo","n/a","wip","dummy","test","temp","temporary","stub","none","null","blank","empty","missing","notext","no text","new text","string","template","sample text","lorem ipsum","fixme","fix me","deprecated","obsolete","removed","deleted","hidden","unused","reserved","...","[placeholder]","{placeholder}","<placeholder>","(placeholder)",}

SYSTEM_PROMPT = """Você é tradutor sênior de jogos Warhammer 40K: Rogue Trader. Traduza do inglês para {lang}.

REGRAS ABSOLUTAS:
1. Preserve TODOS os placeholders §TAG0§, §TAG1§, §TERM0§, §TERM1§ etc. NUNCA os traduza, modifique ou remova.
2. Preserve fórmulas: 1d6, 2d8+5, D100, números e operadores matemáticos.
3. Preserve abreviações de atributos isoladas: INT, STR, AGI, PER, WIL, FEL, TGH, WPN, BAL.
4. Preserve nomes próprios de personagens, locais, facções e títulos únicos do lore.
5. Retorne APENAS um array JSON com as strings traduzidas, na MESMA ordem.

TOM: grimdark, gótico, formal e épico. RPG — termos devem soar naturais para jogadores BR.
{glossary_section}"""


# ─── GLOSSÁRIO INTELIGENTE ───

class SmartGlossary:
    """Glossário que serve para consistência E para decidir preservação."""
    
    def __init__(self, path: Optional[str] = None, preserve_mode: str = "complete",
                 preserve_cats: Set[str] = None):
        self.path = path
        self.preserve_mode = preserve_mode  # "complete" ou "preserve"
        self.preserve_cats = preserve_cats or set(DEFAULT_PRESERVE_CATS)
        self.entries: Dict[str, dict] = {}  # key=term_english.lower()
        self._preserve_index: Set[str] = set()  # pre-computed lowercase keys for O(1) lookup
        self._preserve_terms_list: List[str] = []  # sorted by length desc for contains matching
        self._combined_pattern = None
        self._changed = False
        if path and os.path.exists(path):
            self.load()
    
    def load(self):
        try:
            with open(self.path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            for item in data.get("terms", []):
                self.entries[item["term_english"].lower()] = item
            self._rebuild_index()
            logger.info(f"Glossário: {len(self.entries)} termos carregados.")
        except Exception as e:
            logger.warning(f"Glossário não carregado: {e}")
    
    def _rebuild_index(self):
        """Pre-compute preserve index for fast lookups."""
        self._preserve_index = set()
        self._preserve_terms_list = []
        preserve_cats_lower = {c.lower() for c in self.preserve_cats}
        for key, entry in self.entries.items():
            if entry.get("preserve") or entry.get("category", "").lower() in preserve_cats_lower:
                self._preserve_index.add(key)
                self._preserve_terms_list.append(entry.get("term_english", key))
        # Sort by length descending so longer terms match first (prevents partial matches)
        self._preserve_terms_list.sort(key=len, reverse=True)
        # Pre-build combined regex for O(1) contains matching (instead of 2694 individual regexes)
        self._combined_pattern = None
        if self._preserve_terms_list:
            # Split into batches of 400 terms to avoid overly long regex
            batch_size = 400
            patterns = []
            for i in range(0, len(self._preserve_terms_list), batch_size):
                batch = self._preserve_terms_list[i:i+batch_size]
                escaped = [re.escape(t) for t in batch]
                patterns.append(r'\b(?:' + '|'.join(escaped) + r')\b')
            self._combined_pattern = re.compile('|'.join(patterns), re.IGNORECASE)
    
    def save(self):
        if not self.path or not self._changed:
            return
        data = {
            "metadata": {"updated_at": datetime.now().isoformat(), "total_terms": len(self.entries), "version": "2.0"},
            "terms": sorted(self.entries.values(), key=lambda x: x.get("term_english",""))
        }
        os.makedirs(os.path.dirname(self.path) if os.path.dirname(self.path) else '.', exist_ok=True)
        with open(self.path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        logger.info(f"Glossário salvo: {len(self.entries)} termos.")
    
    def should_preserve(self, text: str) -> bool:
        """True only for EXACT whole-string glossary matches (skip LLM, keep EN)."""
        return self.classify_preserve(text)[0] == "exact"

    def should_preserve_with_terms(self, text: str) -> Tuple[bool, List[str]]:
        """Backward-compatible: True if exact OR inline; terms list always returned.

        Prefer classify_preserve() for new code — it distinguishes exact vs inline.
        """
        kind, terms = self.classify_preserve(text)
        return kind in ("exact", "inline"), terms

    def classify_preserve(self, text: str) -> Tuple[str, List[str]]:
        """Classify text for preserve mode.

        Returns (kind, terms):
          - exact  — whole string IS a glossary preserve term → copy EN, no LLM
          - inline — glossary term(s) embedded in a longer phrase → translate + hard-lock terms
          - clean  — no glossary preserve terms → normal translation

        Glossary source of truth: preserve:true OR category in preserve_cats
        (built into _preserve_index / _combined_pattern).
        """
        if self.preserve_mode == "complete":
            return "clean", []

        text_lower = text.strip().lower()
        if not text_lower:
            return "clean", []

        # --- Exact whole-string match ---
        if text_lower in self._preserve_index:
            entry = self.entries.get(text_lower, {})
            return "exact", [entry.get("term_english", text.strip())]

        text_nohyphen = text_lower.replace("-", " ")
        if text_nohyphen != text_lower and text_nohyphen in self._preserve_index:
            entry = self.entries.get(text_nohyphen, {})
            return "exact", [entry.get("term_english", text_nohyphen)]

        # --- Inline: contains one or more glossary terms (all of them) ---
        if self._combined_pattern is None:
            return "clean", []

        found_terms: List[str] = []
        seen = set()
        for m in self._combined_pattern.finditer(text_lower):
            term_lower = m.group(0).lower()
            if term_lower in self._preserve_index and term_lower not in seen:
                entry = self.entries.get(term_lower, {})
                # Exact-only terms (polysemes): still EN when whole string, not locked inline
                if entry.get("inline", True) is False:
                    continue
                seen.add(term_lower)
                found_terms.append(entry.get("term_english", term_lower))

        if found_terms:
            # longest first — better for TermProtector alternation
            found_terms.sort(key=len, reverse=True)
            return "inline", found_terms

        return "clean", []

    def en_to_pt_map(self) -> Dict[str, str]:
        """EN (original case from glossary) → PT for free fullize replace."""
        out: Dict[str, str] = {}
        for entry in self.entries.values():
            en = (entry.get("term_english") or "").strip()
            pt = (entry.get("term_translated") or "").strip()
            if not en or not pt:
                continue
            # Only entries that participate in preserve index
            if en.lower() not in self._preserve_index:
                continue
            out[en] = pt
        return out

    def format_for_prompt(self, max_terms: int = 80) -> str:
        """Stable glossary block for system prompt (prompt-cache friendly).

        Sorted by English term — never by usage_count (that changes mid-run and
        busts provider cached-input prefixes).
        """
        if not self.entries:
            return ""
        lines = ["\n\nGLOSSÁRIO ATIVO (termos estabelecidos — SIGA):"]
        # Alphabetical = deterministic across the whole job
        ordered = sorted(
            self.entries.values(),
            key=lambda x: (x.get("term_english") or "").lower(),
        )[:max_terms]
        for entry in ordered:
            en = entry.get("term_english", "")
            pt = entry.get("term_translated", "")
            cat = entry.get("category", "")
            lines.append(f'- "{en}" → "{pt}" [{cat}]')
        return "\n".join(lines)

    def format_translation_guide(self, max_terms: int = 100) -> str:
        """Stable consistency guide (also cache-friendly — alpha order)."""
        if not self.entries:
            return ""
        lines = ["\n\nGUIA DE CONSISTÊNCIA (use como referência, mas traduza naturalmente):"]
        ordered = sorted(
            self.entries.values(),
            key=lambda x: (x.get("term_english") or "").lower(),
        )[:max_terms]
        for entry in ordered:
            en = entry.get("term_english", "")
            pt = entry.get("term_translated", "") or en
            cat = entry.get("category", "")
            lines.append(f'- "{en}" [{cat}] → referência PT: "{pt}"')
        lines.append(
            "\nINSTRUÇÃO: os termos acima são apenas referências de consistência. "
            "Traduza o texto de forma natural e localizada, adaptando gênero, número e flexão ao contexto. "
            "NÃO faça substituição literal automática."
        )
        return "\n".join(lines)

    def extract_terms_from_pairs(self, pairs: List[Tuple[str, str]], engine=None, max_terms: int = 20) -> int:
        """Extrai novos termos de pares original→traduzido e adiciona ao glossário.

        Returns the number of new terms added.
        """
        if not engine or not pairs:
            logger.debug("extract_terms_from_pairs skipped: no engine or no pairs")
            return 0

        candidates = engine.extract_terms(pairs, max_terms=max_terms)
        added = 0
        duplicates = 0
        for term in candidates:
            en = term.get("term_english", "").strip().lower()
            if not en:
                continue
            if en in self.entries:
                duplicates += 1
                continue
            self.entries[en] = term
            self._changed = True
            added += 1
            logger.info(f"[AUTO-EXTRACT] Novo termo: {term.get('term_english')} -> {term.get('term_translated')} [{term.get('category')}]")

        if added or duplicates:
            logger.info(f"[AUTO-EXTRACT] Adicionados: {added} | Ja existentes: {duplicates} | Total no glossario: {len(self.entries)}")
            self._rebuild_index()  # rebuild preserve index after new entries
        return added


# ─── PROTEÇÃO DE TAGS (HARD — byte-stable tech markup) ───

class TagProtector:
    """Shield game markup from the LLM via §TAGn§ placeholders.

    Layers:
      1) known paired tags → protect open/close, leave human content visible
      2) known whole tokens (gender, binds, placeholders, sprites…)
      3) blanket leftover ``{…}`` and residual HTML-ish tags
      4) escaped quotes
    """

    # (open)(content)(close) — content stays visible for translation
    PAIRED = [
        (r"(\{g\|[^}]+\})([^{]*)(\{/g\})", "g_tag"),
        (r"(\{d\|[^}]+\})([^{]*)(\{/d\})", "d_tag"),
        (r"(\{n\})([^{]*)(\{/n\})", "n_tag"),
        (r"(\{i\})([^{]*)(\{/i\})", "i_tag"),
        (r"(\{b\})([^{]*)(\{/b\})", "b_tag"),
        (r"(\{u\})([^{]*)(\{/u\})", "u_tag"),
        (r"(<color=[^>]+>)([^<]*)(</color>)", "color_tag"),
        (r"(<b>)([^<]*)(</b>)", "html_b"),
        (r"(<i>)([^<]*)(</i>)", "html_i"),
        (r"(<u>)([^<]*)(</u>)", "html_u"),
        (r"(<link=[^>]+>)([^<]*)(</link>)", "link_tag"),
        (r"(<indent[^>]*>)(.*?)(</indent>)", "indent_tag"),
        (r"(<nobr>)(.*?)(</nobr>)", "nobr_tag"),
        (r"(<uppercase>)(.*?)(</uppercase>)", "uppercase_tag"),
        (r"(<align[^>]*>)(.*?)(</align>)", "align_tag"),
    ]

    # Entire match → one placeholder. Specific pipes before blanket \{[^{}]+\}
    WHOLE = [
        r"\{mf\|[^}]+\}",
        r"\{rt_mf\|[^}]+\}",
        r"\{bind\|[^}]+\}",
        r"\{mouse_icon\|[^}]+\}",
        r"\{console_bind\|[^}]+\}",
        r"\{unit_stat\|[^}]+\}",
        r"\{uip\|[^}]+\}",
        r"\{console_icon\|[^}]+\}",
        r"\{pc_bind\|[^}]+\}",
        r"\{\{[^{}]*\}\}",
        r"\{[^{}]+\}",  # {name}, {0}, {br}, orphans…
        r"<sprite\b[^>]*/?>",
        r"<size\b[^>]*>",
        r"</size>",
        r"<alpha\b[^>]*>",
        r"<br\s*/?>",
        r"</?[A-Za-z][^>]*>",  # residual HTML
    ]

    @staticmethod
    def protect(text: str) -> Tuple[str, Dict[str, str]]:
        if not text:
            return text, {}
        ph: Dict[str, str] = {}
        counter = [0]

        def _ph() -> str:
            p = f"§TAG{counter[0]}§"
            counter[0] += 1
            return p

        result = text

        for pattern, _ in TagProtector.PAIRED:
            def make_paired():
                def repl(m):
                    po, pc = _ph(), _ph()
                    ph[po] = m.group(1)
                    ph[pc] = m.group(3)
                    return f"{po}{m.group(2)}{pc}"
                return repl
            result = re.sub(pattern, make_paired(), result, flags=re.IGNORECASE | re.DOTALL)

        for pattern in TagProtector.WHOLE:
            def make_whole():
                def repl(m):
                    p = _ph()
                    ph[p] = m.group(0)
                    return p
                return repl
            result = re.sub(pattern, make_whole(), result, flags=re.IGNORECASE)

        def quote_repl(m):
            p = _ph()
            ph[p] = m.group(0)
            return p
        result = re.sub(r'\\"', quote_repl, result)

        return result, ph

    @staticmethod
    def restore(text: str, ph: Dict[str, str]) -> str:
        if not text or not ph:
            return text
        result = text
        for p in sorted(ph.keys(), key=lambda x: int(re.search(r"\d+", x).group()), reverse=True):
            result = result.replace(p, ph[p])
        return result

    @staticmethod
    def leak_scan(text: str) -> List[str]:
        """Leftover tech-looking tokens after protect (tests/audit)."""
        protected, _ = TagProtector.protect(text)
        leaks = []
        for m in re.finditer(r"\{[^{}]+\}", protected):
            leaks.append(m.group(0))
        for m in re.finditer(r"</?[A-Za-z][^>]*>", protected):
            leaks.append(m.group(0))
        return leaks


class TermProtector:
    """Hard-lock glossary terms inside a phrase (same idea as TagProtector).

    Placeholders use plain ASCII [[W40KTn]] — LLMs mangle §TERM less often,
    and restore also accepts legacy §TERM / $TERM forms.
    """

    _PH_RE = re.compile(
        r"\[\[W40KT(\d+)\]\]|§TERM(\d+)§|\$TERM(\d+)\$",
        re.IGNORECASE,
    )

    @staticmethod
    def _ph_token(i: int) -> str:
        return f"[[W40KT{i}]]"

    @staticmethod
    def protect(text: str, terms: List[str]) -> Tuple[str, Dict[str, str]]:
        if not text or not terms:
            return text, {}
        uniq = sorted({t for t in terms if t}, key=len, reverse=True)
        if not uniq:
            return text, {}
        pattern = re.compile(
            r"\b(?:" + "|".join(re.escape(t) for t in uniq) + r")\b",
            re.IGNORECASE,
        )
        matches = list(pattern.finditer(text))
        if not matches:
            return text, {}
        ph: Dict[str, str] = {}
        result = text
        # Replace from the end so offsets stay valid; index 0 = first left-to-right match
        # Store both forward index (stable for LLM) via enumerate(matches) not reversed index
        # Build left-to-right ids, apply right-to-left replacements
        ltr = list(matches)
        for i, m in enumerate(ltr):
            ph[TermProtector._ph_token(i)] = m.group(0)
        for i, m in enumerate(reversed(ltr)):
            # reversed i → original index
            orig_i = len(ltr) - 1 - i
            p = TermProtector._ph_token(orig_i)
            result = result[: m.start()] + p + result[m.end() :]
        return result, ph

    @staticmethod
    def restore(text: str, ph: Dict[str, str]) -> str:
        if not text or not ph:
            return text
        result = text
        # 1) exact keys (TAG + TERM)
        for p in sorted(ph.keys(), key=len, reverse=True):
            if p in result:
                result = result.replace(p, ph[p])
        # 2) index map for term placeholders (handles LLM renumber / § vs $ vs [[ ]])
        by_idx: Dict[int, str] = {}
        for k, v in ph.items():
            m = re.search(r"(?:W40KT|TERM)(\d+)", k, re.I)
            if m:
                by_idx[int(m.group(1))] = v

        def _repl(m: re.Match) -> str:
            idx = m.group(1) or m.group(2) or m.group(3)
            if idx is None:
                return m.group(0)
            return by_idx.get(int(idx), m.group(0))

        result = TermProtector._PH_RE.sub(_repl, result)
        # 3) leftover term ph → drop empty rather than show junk (last resort)
        result = re.sub(r"\[\[W40KT\d+\]\]|§TERM\d+§|\$TERM\d+\$", "", result)
        return result


# ─── Gender tags {mf|male|female} / {rt_mf|…} ───
# Game picks side by PC sex. BOTH sides must be PT — never leave him/her.

_MF_PAIR_MAP = {
    # pronouns
    ("he", "she"): ("ele", "ela"),
    ("him", "her"): ("ele", "ela"),
    ("his", "her"): ("seu", "sua"),
    ("his", "hers"): ("dele", "dela"),
    ("himself", "herself"): ("si mesmo", "si mesma"),
    # titles
    ("lord", "lady"): ("lorde", "lady"),
    ("lordship", "ladyship"): ("senhoria", "senhoria"),
    ("his lordship", "her ladyship"): ("sua senhoria", "sua senhoria"),
    ("his lord", "her lady"): ("seu lorde", "sua lady"),
    ("master", "mistress"): ("mestre", "mestra"),
    ("sir", "ma'am"): ("senhor", "senhora"),
    ("sir", "lady"): ("senhor", "lady"),
    ("m'lord", "m'lady"): ("milorde", "milady"),
    ("man", "woman"): ("homem", "mulher"),
    ("boy", "girl"): ("rapaz", "moça"),
    ("brother", "sister"): ("irmão", "irmã"),
    ("layman", "laywoman"): ("leigo", "leiga"),
    ("lordiness", "ladyness"): ("senhoria", "senhoria"),
    ("lordliness", "ladyness"): ("senhoria", "senhoria"),
    # broken partials sometimes seen
    ("im", "er"): ("ele", "ela"),
    ("is", "er"): ("seu", "sua"),
}


def _mf_case_match(src: str, dst: str) -> str:
    """Apply src casing style onto dst."""
    if not src:
        return dst
    if src.isupper():
        return dst.upper()
    if src[0].isupper():
        return dst[:1].upper() + dst[1:] if dst else dst
    return dst


def localize_gender_tags(text: str) -> str:
    """Translate both sides of {mf|a|b} / {rt_mf|a|b} using a fixed pair map."""
    if not text or "{mf|" not in text.lower() and "{rt_mf|" not in text.lower():
        # fast path
        if "{mf|" not in text and "{rt_mf|" not in text:
            return text

    def repl(m: re.Match) -> str:
        prefix = m.group(1)  # mf or rt_mf
        a, b = m.group(2), m.group(3)
        key = (a.lower(), b.lower())
        if key in _MF_PAIR_MAP:
            pa, pb = _MF_PAIR_MAP[key]
            return "{" + prefix + "|" + _mf_case_match(a, pa) + "|" + _mf_case_match(b, pb) + "}"
        # already non-English-looking sides — leave
        return m.group(0)

    return re.sub(
        r"\{(mf|rt_mf)\|([^|}]+)\|([^}]+)\}",
        repl,
        text,
        flags=re.IGNORECASE,
    )


def scrub_leaked_term_placeholders(text: str) -> str:
    """Remove any leftover term locks that escaped restore."""
    if not text:
        return text
    return re.sub(r"\[\[W40KT\d+\]\]|§TERM\d+§|\$TERM\d+\$", "", text)



def fullize_text(text: str, en_to_pt: Dict[str, str]) -> str:
    """Free replace: glossary EN terms → term_translated (longest-first, word boundary)."""
    if not text or not en_to_pt:
        return text
    # Longest EN first
    items = sorted(en_to_pt.items(), key=lambda kv: len(kv[0]), reverse=True)
    # Skip no-ops (EN == PT) — nothing to do
    items = [(en, pt) for en, pt in items if en != pt]
    if not items:
        return text
    pattern = re.compile(
        r"\b(?:" + "|".join(re.escape(en) for en, _ in items) + r")\b",
        re.IGNORECASE,
    )
    lower_map = {en.lower(): pt for en, pt in items}

    def repl(m: re.Match) -> str:
        return lower_map.get(m.group(0).lower(), m.group(0))

    return pattern.sub(repl, text)


def fullize_file(input_path: str, output_path: str, glossary_path: str) -> int:
    """Build Full track from Preserved track via free glossary replace (no LLM)."""
    data = load_json(input_path)
    if not data or "strings" not in data:
        logger.error("Arquivo inválido para --fullize")
        return 1
    glossary = SmartGlossary(glossary_path, preserve_mode="preserve")
    en_to_pt = glossary.en_to_pt_map()
    if not en_to_pt:
        logger.warning("Nenhum par EN→PT no glossário para fullize.")
    changed = 0
    for key, val in data["strings"].items():
        if not isinstance(val, dict):
            continue
        old = val.get("Text", "")
        new = fullize_text(old, en_to_pt)
        if new != old:
            val["Text"] = new
            val.pop("_preserved", None)
            val["_fullized"] = True
            changed += 1
    atomic_save(data, output_path)
    logger.info(f"Fullize: {changed} strings altered | out={output_path} | glossary pairs={len(en_to_pt)}")
    return 0


# ─── ENGINE DE TRADUÇÃO ───

class TranslationEngine:
    def __init__(self, model="deepseek-chat", temperature=0.15, api_key: Optional[str] = None, base_url: Optional[str] = None):
        self.model = model
        self.temperature = temperature
        self.api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        self.base_url = base_url or os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
        self._client = None
        self._ensure_client()

    def _ensure_client(self):
        if self._client is not None:
            return True
        try:
            from openai import OpenAI
            if not self.api_key:
                logger.error("DEEPSEEK_API_KEY não configurada."); return False
            # max_retries=1: o retry com backoff já existe no nível do batch
            # (translate_batch). Sem isso, o SDK repete cada chamada 2x por
            # dentro — em rate-limit, workers "paralelos" viram fila de sleeps.
            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url,
                                  max_retries=1)
            return True
        except ImportError:
            logger.error("pip install openai"); return False
    
    def translate_batch(self, texts: List[str], system_prompt: str, keys=None, user_extra: str = "") -> Optional[List[str]]:
        if not self._ensure_client() or not texts:
            return None
        
        user = f"Traduza cada string para {DEFAULT_TARGET_LANGUAGE}. Preserve §TAGx§ and §TERMx§ placeholders unchanged.{user_extra}\n\n```json\n{json.dumps(texts, ensure_ascii=False)}\n```"
        
        for attempt in range(DEFAULT_MAX_RETRIES):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[{"role":"system","content":system_prompt},{"role":"user","content":user}],
                    temperature=self.temperature,
                    response_format={"type":"json_object"}
                )
                content = resp.choices[0].message.content or ""
                content = content.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip()
                parsed = json.loads(content)
                
                if isinstance(parsed, list):
                    translated = parsed
                elif isinstance(parsed, dict):
                    translated = None
                    for v in parsed.values():
                        if isinstance(v, list):
                            translated = v; break
                    if translated is None:
                        translated = list(parsed.values())
                else:
                    raise ValueError(f"Formato inesperado: {type(parsed)}")
                
                if len(translated) != len(texts):
                    logger.warning(f"Divergência: enviado={len(texts)}, retornado={len(translated)}. Tentativa {attempt+1}.")
                    time.sleep(10 * (attempt+1))
                    continue
                return translated
                
            except Exception as e:
                logger.warning(f"Erro API: {e}. Tentativa {attempt+1}/{DEFAULT_MAX_RETRIES}.")
                time.sleep(15 * (attempt+1))
        return None

    def extract_terms(self, pairs: List[Tuple[str, str]], max_terms: int = 20) -> List[Dict[str, str]]:
        """Ask the LLM to extract new glossary terms from original->translated pairs.

        Returns a list of candidate dicts with term_english, term_translated, category, source.
        """
        if not self._ensure_client() or not pairs:
            logger.debug("extract_terms skipped: no client or no pairs")
            return []

        logger.info(f"[AUTO-EXTRACT] Enviando {len(pairs)} pares para o LLM ({self.model})...")

        # Build a compact JSON list of pairs
        samples = [{"en": en, "pt": pt} for en, pt in pairs[:60]]  # limit context
        user = (
            "You are extracting glossary terms for a Warhammer 40K: Rogue Trader translation.\n"
            "Look at these original English → translated Portuguese pairs and identify game-specific terms.\n"
            "Include: proper names, item names, abilities, talents, skills, attributes, locations, factions, titles, and mechanics.\n"
            "Do NOT include common words, narrative filler, or fully translated generic phrases.\n"
            "Return ONLY a JSON array of objects with the exact keys:\n"
            '[{"term_english": "Plasma Gun", "term_translated": "Plasma Gun", "category": "weapon"}]\n\n'
            "Pairs:\n"
            f"{json.dumps(samples, ensure_ascii=False)}"
        )
        system = (
            "You are a glossary extractor for Warhammer 40K: Rogue Trader. "
            "Categories MUST be one of: weapon, talent, ability, skill, attribute, armour, helmet, "
            "gloves, cloak, boots, necklace, accessory, consumable, pet_protocol, conviction, archetype, "
            "homeworld, origin, lore, faction, location, character, other. "
            "If the Portuguese translation is obvious and localized, use it; otherwise keep the English term in term_translated. "
            "Return ONLY valid JSON. No explanations."
        )

        for attempt in range(2):
            try:
                resp = self._client.chat.completions.create(
                    model=self.model,
                    messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                    temperature=0.1,
                    response_format={"type": "json_object"}
                )
                content = resp.choices[0].message.content or ""
                content = content.strip().removeprefix('```json').removeprefix('```').removesuffix('```').strip()
                logger.debug(f"[AUTO-EXTRACT] Raw LLM response: {content[:500]}")
                parsed = json.loads(content)

                if isinstance(parsed, list):
                    terms = parsed
                elif isinstance(parsed, dict):
                    terms = None
                    for v in parsed.values():
                        if isinstance(v, list):
                            terms = v
                            break
                    if terms is None:
                        terms = list(parsed.values())
                else:
                    logger.warning(f"[AUTO-EXTRACT] Unexpected response type: {type(parsed)}")
                    return []

                logger.info(f"[AUTO-EXTRACT] LLM retornou {len(terms)} candidatos.")

                # Normalize and filter
                valid = []
                for t in terms[:max_terms]:
                    if not isinstance(t, dict):
                        logger.debug(f"[AUTO-EXTRACT] Skipping non-dict term: {t}")
                        continue
                    en = str(t.get("term_english", t.get("en", ""))).strip()
                    pt = str(t.get("term_translated", t.get("pt", t.get("pt_br", "")))).strip() or en
                    cat = str(t.get("category", "other")).strip().lower()
                    if not en or len(en) <= 1:
                        logger.debug(f"[AUTO-EXTRACT] Skipping short/empty term: {t}")
                        continue
                    valid.append({
                        "term_english": en,
                        "term_translated": pt,
                        "category": cat,
                        "source": "auto",
                        "context": "Auto-extracted during translation",
                        "confidence": "medium",
                        "preserve": False,
                        "usage_count": 1,
                        "created_at": datetime.now().isoformat(),
                    })

                logger.info(f"[AUTO-EXTRACT] {len(valid)} candidatos validos apos filtro.")
                return valid

            except Exception as e:
                logger.warning(f"[AUTO-EXTRACT] Erro extração de termos: {e}. Tentativa {attempt+1}/2.")
                if attempt == 0:
                    time.sleep(3)
        return []


# ─── UTILITÁRIOS ───

def atomic_save(data: Any, path: str):
    dn = os.path.dirname(path) or "."
    os.makedirs(dn, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=dn, delete=False) as t:
        json.dump(data, t, indent=2, ensure_ascii=False)
        tmp = t.name
    shutil.move(tmp, path)

def load_json(path: str) -> Optional[dict]:
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return None

def load_blacklist(path: Optional[str]) -> Set[str]:
    """Carrega uma lista de UUIDs (ou dict de UUIDs) a serem pulados."""
    if not path or not os.path.exists(path):
        return set()
    try:
        with open(path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, list):
            return set(str(x) for x in data)
        if isinstance(data, dict):
            return set(str(k) for k in data.keys())
    except Exception as e:
        logger.warning(f"Blacklist não carregada: {e}")
    return set()


def should_skip(text: str) -> bool:
    """Empty / placeholder junk — never send to LLM."""
    if not text or not text.strip():
        return True
    clean = text.strip().lower()
    clean = re.sub(r'^[\[\{<\(]+|[\]\}>\)]+$', '', clean)
    return clean in SKIP_TEXTS


EULA_KEYWORDS = (
    "eula", "end user license", "license agreement",
    "terms of service", "privacy policy", "copyright",
    "registered trademark", "all rights reserved",
)


def is_eula(text: str) -> bool:
    """True EULA/legal walls only — not normal RPG narrative.

    Thresholds (same as GUI Pre-Scan):
      - >15000 chars → EULA
      - >3000 chars and >2000 words → EULA
      - >3000 chars, keyword hit, and >500 words → EULA
    """
    if not text:
        return False
    n = len(text)
    if n > 15000:
        return True
    if n <= 3000:
        return False
    words = text.split()
    wc = len(words)
    if wc > 2000:
        return True
    lower = text.lower()
    if wc > 500 and any(kw in lower for kw in EULA_KEYWORDS):
        return True
    return False


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)

def split_batch(batch, max_tok=MAX_TOKENS_PER_BATCH):
    if not batch:
        return []
    result, cur, cur_tok = [], [], 0
    for key, value in batch:
        t = estimate_tokens(value.get("Text",""))
        if t > max_tok:
            if cur:
                result.append(cur); cur=[]; cur_tok=0
            result.append([(key,value)])
            continue
        if cur_tok + t > max_tok and cur:
            result.append(cur); cur=[]; cur_tok=0
        cur.append((key,value)); cur_tok += t
    if cur:
        result.append(cur)
    return result


# ─── PROCESSAMENTO DE BATCH ───

_thread_local = threading.local()

def get_engine(model, temp):
    if not hasattr(_thread_local, 'engine') or _thread_local.engine is None:
        _thread_local.engine = TranslationEngine(model=model, temperature=temp)
    return _thread_local.engine

def process_batch(batch: List[Tuple[str,dict]], system_prompt: str, model: str, temp: float, dry_run: bool):
    try:
        keys = [k for k, _ in batch]
        originals = [v["Text"] for _, v in batch]
        offsets = [v.get("Offset", 0) for _, v in batch]

        # 1) game tags  2) glossary terms (inline preserve)
        protected: List[str] = []
        ph_list: List[Dict[str, str]] = []
        for (_, v), original in zip(batch, originals):
            t, ph = TagProtector.protect(original)
            terms = v.get("_preserve_terms") or []
            if terms:
                t, tph = TermProtector.protect(t, terms)
                ph.update(tph)
            protected.append(t)
            ph_list.append(ph)

        if dry_run:
            translated = protected
        else:
            engine = get_engine(model, temp)
            translated = engine.translate_batch(protected, system_prompt, keys, user_extra="")

        if translated is None:
            return None

        data: Dict[str, dict] = {}
        for i, key in enumerate(keys):
            restored = TagProtector.restore(translated[i], ph_list[i])
            # Term locks may use [[W40KTn]] / legacy §TERM — restore via combined ph
            restored = TermProtector.restore(restored, ph_list[i])
            restored = localize_gender_tags(restored)
            restored = scrub_leaked_term_placeholders(restored)
            data[key] = {"Offset": offsets[i], "Text": restored}
        return data
    except Exception as e:
        logger.error(f"process_batch error: {e}")
        return None


# ─── MAIN ───

def main():
    parser = argparse.ArgumentParser(description="Tradutor JSON de Jogos v3.0")
    parser.add_argument("-i","--input", required=True, help="Arquivo original")
    parser.add_argument("-o","--output", required=True, help="Arquivo de saída")
    parser.add_argument("-g","--glossary", help="Glossário JSON")
    parser.add_argument("--mode", choices=["complete","preserve"], default="complete",
                        help="complete=traduz tudo | preserve=exact EN + inline term lock")
    parser.add_argument("--preserve-cats", default=DEFAULT_PRESERVE_CATS_CSV,
                        help="Categorias do glossário a preservar (modo preserve)")
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("-b","--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("-w","--workers", type=int, default=None,
                        help="Threads paralelas. Omitido/<=0 = auto (model profile).")
    parser.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    parser.add_argument("--extract-every", type=int, default=0)
    parser.add_argument("--blacklist", help="JSON com lista de UUIDs (ou dict) para pular na tradução")
    parser.add_argument("--preserve-map", dest="preserve_map", default="preserve_map.json",
                        help="UUID → {kind, terms} map written in preserve mode")
    parser.add_argument("--retranslate-map", dest="retranslate_map",
                        help="JSON com UUIDs a retraduzir (legado). Prefira --fullize para track Full.")
    parser.add_argument("--fullize", action="store_true",
                        help="Free EN→PT glossary replace (no LLM). Input=preserved PT, output=full PT.")
    parser.add_argument("--auto-glossary", action="store_true",
                        help="Forca extracao de termos para o glossario mesmo em dry-run (usado pelo botao Populate Glossary)")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--model", default="deepseek-v4-flash")
    parser.add_argument("--prescan-cache", dest="prescan_cache", default="prescan_cache.json",
                        help="JSON cache from Pre-Scan (skips re-classification of preserved/skip/eula UUIDs)")
    parser.add_argument("--optimized-batch", action="store_true", default=True,
                        help="Smart tier batch sizes from model profile. On by default.")
    parser.add_argument("--no-optimized-batch", action="store_false", dest="optimized_batch",
                        help="Disable smart tier sizes; derive from --batch-size only.")
    parser.add_argument("--no-profile", action="store_true",
                        help="Ignore model_profiles (use raw -w/-b and default token cap).")
    parser.add_argument("--save-every", type=int, default=0,
                        help="Write output every N batches (0=from model profile).")
    args = parser.parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    # ── Model profile (batch tiers / workers / save cadence / token budget) ──
    try:
        from model_profiles import (
            resolve_profile,
            batch_tiers,
            recommended_workers,
            save_every_batches,
            max_tokens_per_batch,
            profile_summary,
        )
        _HAVE_PROFILES = True
    except ImportError:
        _HAVE_PROFILES = False

    profile_workers = args.workers
    profile_save_every = args.save_every if args.save_every > 0 else 1
    profile_max_tok = MAX_TOKENS_PER_BATCH
    profile_batches = None  # type: ignore

    if _HAVE_PROFILES and not args.no_profile:
        rid, _p = resolve_profile(args.model)
        # Auto-bump só quando -w não foi passado (None) ou a GUI mandou
        # "auto" (<=0). Um -w explícito é respeitado literalmente — é assim
        # que os overrides de workers das Configurações chegam ao engine.
        if args.workers is None or args.workers <= 0:
            profile_workers = recommended_workers(args.model)
            args.workers = profile_workers
        if args.save_every <= 0:
            profile_save_every = save_every_batches(args.model)
        else:
            profile_save_every = args.save_every
        profile_max_tok = max_tokens_per_batch(args.model)
        if args.optimized_batch:
            profile_batches = batch_tiers(args.model, optimized=True)
        logger.info(f"Model profile: {profile_summary(args.model)}")
        logger.info(
            f"Cache tip: system+glossary prefix is stable (alpha glossary). "
            f"Only the user batch JSON changes → provider cached-input."
        )
    else:
        if args.save_every > 0:
            profile_save_every = args.save_every
        logger.info("Model profiles disabled or missing — using CLI defaults.")

    # Guard: CLI values <= 0 mean "auto" (GUI spins default to 0). Never let them
    # reach ThreadPoolExecutor(max_workers=0) or the batch-size math.
    if args.workers is None or args.workers <= 0:
        args.workers = DEFAULT_MAX_WORKERS
    if args.batch_size is None or args.batch_size <= 0:
        args.batch_size = DEFAULT_BATCH_SIZE
    # save_every is already normalized above (<=0 → model profile / 1).

    logger.info(
        f"Config: model={args.model} | mode={args.mode} | batch={args.batch_size} | "
        f"workers={args.workers} | temp={args.temperature} | save_every={profile_save_every} | dry_run={args.dry_run}"
    )

    # Free fullize path (no LLM)
    if args.fullize:
        if not args.glossary:
            logger.error("--fullize requires -g/--glossary")
            return 1
        return fullize_file(args.input, args.output, args.glossary)

    # ── CARREGA ──
    input_data = load_json(args.input)
    if not input_data or "strings" not in input_data:
        logger.error("Arquivo inválido"); return 1
    
    preserve_cats = set(c.strip().lower() for c in args.preserve_cats.split(","))
    glossary = SmartGlossary(args.glossary, args.mode, preserve_cats)
    blacklist = load_blacklist(args.blacklist)
    if blacklist:
        logger.info(f"Blacklist: {len(blacklist)} UUIDs serão pulados.")
    
    # ── PRE-SCAN CACHE: skip re-classification for known preserved/skip/eula UUIDs ──
    prescan_preserved: Set[str] = set()
    prescan_skip: Set[str] = set()
    prescan_eula: Set[str] = set()
    if args.prescan_cache and os.path.exists(args.prescan_cache):
        try:
            with open(args.prescan_cache, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            buckets = cache.get("buckets", {})
            prescan_preserved = set(buckets.get("PRESERVED", []))
            prescan_skip = set(buckets.get("SKIP", []))
            prescan_eula = set(buckets.get("EULA", []))
            # Verify source hasn't changed
            import hashlib
            src_hash = hashlib.md5(open(args.input, "rb").read()).hexdigest()
            if cache.get("source_hash") != src_hash:
                logger.warning("Pre-Scan cache is stale (source file changed). Ignoring.")
                prescan_preserved.clear(); prescan_skip.clear(); prescan_eula.clear()
            elif cache.get("preserve_mode", "preserve") != args.mode:
                logger.warning(f"Pre-Scan cache mode ({cache.get('preserve_mode')}) differs from current mode ({args.mode}). "
                              "PRESERVED entries ignored (re-classifying). SKIP/EULA still used.")
                prescan_preserved.clear()  # re-classify preserved, but keep skip/eula
            else:
                logger.info(f"Pre-Scan cache loaded: {len(prescan_preserved)} preserved, "
                           f"{len(prescan_skip)} skip, {len(prescan_eula)} eula (O(1) lookup)")
        except Exception as e:
            logger.warning(f"Pre-Scan cache not used: {e}")
    
    orig_strings = input_data["strings"]

    # Modo segunda passada: traduzir apenas UUIDs que foram preservados antes
    retranslate_keys: Optional[Set[str]] = None
    retranslate_terms: Dict[str, List[str]] = {}
    if args.retranslate_map:
        try:
            with open(args.retranslate_map, 'r', encoding='utf-8') as f:
                rmap = json.load(f)
            if isinstance(rmap, dict):
                retranslate_keys = set(rmap.keys())
                retranslate_terms = {}
                for k, v in rmap.items():
                    if isinstance(v, list):
                        retranslate_terms[k] = v
                    elif isinstance(v, dict):
                        retranslate_terms[k] = list(v.get("terms") or [])
                    else:
                        retranslate_terms[k] = [str(v)]
            elif isinstance(rmap, list):
                retranslate_keys = set(str(x) for x in rmap)
            else:
                logger.error("--retranslate-map deve ser um dict {uuid: ...} ou uma lista de UUIDs")
                return 1
            orig_strings = {k: v for k, v in orig_strings.items() if k in retranslate_keys}
            logger.info(f"🔁 Retranslate map: {len(orig_strings)} UUIDs selecionados de {args.retranslate_map}")
        except Exception as e:
            logger.error(f"Erro ao carregar retranslate-map: {e}")
            return 1

    logger.info(f"Entrada: {len(orig_strings)} strings | Modo: {args.mode} | Preservar: {preserve_cats}")
    
    # ── PREPARA SAÍDA ──
    output_data = {"strings": {}}
    translated = {}
    if args.resume and os.path.exists(args.output):
        existing = load_json(args.output)
        if existing and "strings" in existing:
            translated = existing["strings"]
            logger.info(f"Resume: {len(translated)} itens já processados")
    
    # ── CLASSIFICA ──
    pending = []
    skipped = 0
    preserved_exact = 0
    preserved_inline = 0
    already_done = 0
    # New shape: uuid → {"kind": "exact"|"inline", "terms": [...]}
    preserve_map: Dict[str, dict] = {}
    
    for key, value in orig_strings.items():
        text = value.get("Text", "")
        
        # ── PRE-SCAN CACHE (O(1) lookups — skip expensive checks) ──
        # prescan PRESERVED = exact-only (legacy); treat as exact skip
        if key in prescan_eula:
            translated[key] = {"Offset": value.get("Offset",0), "Text": text, "_skipped": "eula"}
            skipped += 1
            continue
        
        if key in prescan_skip:
            translated[key] = {"Offset": value.get("Offset",0), "Text": text, "_skipped": "prescan_skip"}
            skipped += 1
            continue
        
        if key in prescan_preserved:
            translated[key] = {"Offset": value.get("Offset",0), "Text": text, "_preserved": True, "_preserve_kind": "exact"}
            preserve_map[key] = {"kind": "exact", "terms": ["prescan_cache"]}
            preserved_exact += 1
            continue
        
        # Blacklist explícita de UUIDs (EULA, termos legais, etc.)
        if key in blacklist:
            translated[key] = {"Offset": value.get("Offset",0), "Text": text, "_skipped": "blacklist"}
            skipped += 1
            continue
        
        # Placeholder / vazio — free skip
        if should_skip(text):
            translated[key] = {"Offset": value.get("Offset",0), "Text": text, "_skipped": "placeholder"}
            skipped += 1
            continue

        # EULA / license walls — free skip (no API). Same thresholds as GUI Pre-Scan.
        if is_eula(text):
            translated[key] = {"Offset": value.get("Offset",0), "Text": text, "_skipped": "eula"}
            skipped += 1
            continue
        
        # Já traduzido (resume)?
        if key in translated and translated[key].get("Text") and not translated[key].get("_failed"):
            already_done += 1
            continue
        
        # Preserve mode: exact = skip LLM; inline = queue with term locks; clean = normal
        if args.mode == "preserve":
            kind, terms = glossary.classify_preserve(text)
            if kind == "exact":
                translated[key] = {
                    "Offset": value.get("Offset", 0),
                    "Text": text,
                    "_preserved": True,
                    "_preserve_kind": "exact",
                }
                preserve_map[key] = {"kind": "exact", "terms": terms}
                preserved_exact += 1
                continue
            if kind == "inline":
                # Copy value and attach terms for TermProtector in process_batch
                v2 = dict(value)
                v2["_preserve_terms"] = terms
                pending.append((key, v2))
                preserve_map[key] = {"kind": "inline", "terms": terms}
                preserved_inline += 1
                continue

        pending.append((key, value))
    
    logger.info(
        f"Pendentes: {len(pending)} | Exact EN: {preserved_exact} | "
        f"Inline locked: {preserved_inline} | Já feitos: {already_done} | Pulados: {skipped}"
    )
    
    if not pending:
        logger.info("Nada para traduzir!")
        output_data["strings"] = translated
        atomic_save(output_data, args.output)
        return 0
    
    # ── PREPARA BATCHES (smart adaptive sizing) ──
    # Classify pending strings by length to optimize batch sizes.
    # Short strings → big batches (less API overhead per string).
    # Long strings → small batches (avoid token overflow, better quality).
    SHORT_THRESHOLD = 50    # chars
    MEDIUM_THRESHOLD = 300  # chars
    LONG_THRESHOLD = 1000   # chars
    
    short_pending = []
    medium_pending = []
    long_pending = []
    xlong_pending = []
    
    for item in pending:
        text_len = len(item[1].get("Text", ""))
        if text_len <= SHORT_THRESHOLD:
            short_pending.append(item)
        elif text_len <= MEDIUM_THRESHOLD:
            medium_pending.append(item)
        elif text_len <= LONG_THRESHOLD:
            long_pending.append(item)
        else:
            xlong_pending.append(item)
    
    # Adaptive batch sizes: bigger for short strings, smaller for long
    # Adaptive batch sizes from model profile (or legacy defaults)
    if args.optimized_batch and profile_batches:
        SHORT_BATCH, MEDIUM_BATCH, LONG_BATCH, XLONG_BATCH = profile_batches
        logger.info(
            f"Optimized batching (profile): short×{SHORT_BATCH} med×{MEDIUM_BATCH} "
            f"long×{LONG_BATCH} xlong×{XLONG_BATCH}"
        )
    elif args.optimized_batch:
        SHORT_BATCH = 50
        MEDIUM_BATCH = 30
        LONG_BATCH = 12
        XLONG_BATCH = 5
        logger.info("Optimized batching: default tier sizes (50/30/12/5)")
    else:
        SHORT_BATCH = min(50, max(args.batch_size * 3, 30))
        MEDIUM_BATCH = min(30, max(args.batch_size, 12))
        LONG_BATCH = min(12, max(args.batch_size // 2, 6))
        XLONG_BATCH = min(5, max(2, args.batch_size // 4))

    tok_cap = profile_max_tok if profile_max_tok else MAX_TOKENS_PER_BATCH
    logger.info(
        f"Smart batches: short({len(short_pending)})×{SHORT_BATCH} | "
        f"medium({len(medium_pending)})×{MEDIUM_BATCH} | "
        f"long({len(long_pending)})×{LONG_BATCH} | "
        f"xlong({len(xlong_pending)})×{XLONG_BATCH} | tok_cap={tok_cap}"
    )
    
    batches_raw = []
    if short_pending:
        batches_raw.extend(short_pending[i:i+SHORT_BATCH] for i in range(0, len(short_pending), SHORT_BATCH))
    if medium_pending:
        batches_raw.extend(medium_pending[i:i+MEDIUM_BATCH] for i in range(0, len(medium_pending), MEDIUM_BATCH))
    if long_pending:
        batches_raw.extend(long_pending[i:i+LONG_BATCH] for i in range(0, len(long_pending), LONG_BATCH))
    if xlong_pending:
        batches_raw.extend(xlong_pending[i:i+XLONG_BATCH] for i in range(0, len(xlong_pending), XLONG_BATCH))
    
    batches = []
    for raw in batches_raw:
        tok = sum(estimate_tokens(v.get("Text","")) for _,v in raw)
        if tok > tok_cap:
            batches.extend(split_batch(raw, max_tok=tok_cap))
        else:
            batches.append(raw)
    
    logger.info(f"Batches: {len(batches)} (was ~{len(pending)//args.batch_size} with fixed batch_size={args.batch_size})")
    
    # ── SYSTEM PROMPT ──
    if args.retranslate_map:
        # Segunda passada: traduzir preservados com contexto localizado
        glossary_section = glossary.format_translation_guide() if glossary.entries else ""
        system_prompt = SYSTEM_PROMPT.format(lang=DEFAULT_TARGET_LANGUAGE, glossary_section=glossary_section)
        system_prompt += (
            "\n\nVOCÊ ESTÁ NA SEGUNDA PASSADA DE TRADUÇÃO: anteriormente estes textos "
            "tiveram nomes de itens/habilidades/talentos preservados em inglês. Agora traduza o texto "
            "completamente para português, mantendo a consistência com o glossário, mas de forma "
            "natural e localizada."
        )
    else:
        glossary_section = glossary.format_for_prompt() if glossary.entries else ""
        system_prompt = SYSTEM_PROMPT.format(lang=DEFAULT_TARGET_LANGUAGE, glossary_section=glossary_section)
    
    # ── PROCESSA ──
    success = 0
    failed = 0
    batches_done = 0
    recent_pairs: List[Tuple[str, str]] = []
    extraction_engine = None
    enable_extraction = (
        args.extract_every > 0
        and glossary.path
        and (not args.dry_run or args.auto_glossary)
    )
    if enable_extraction:
        extraction_engine = get_engine(args.model, args.temperature)
        if extraction_engine and extraction_engine._ensure_client():
            mode_label = "(dry-run glossary population)" if args.dry_run else "(during translation)"
            logger.info(f"Auto-extracao habilitada {mode_label}: a cada {args.extract_every} batches o LLM sugere novos termos para o glossario.")
        else:
            logger.warning("Auto-extracao desabilitada: API key nao configurada.")
            extraction_engine = None

    with tqdm(total=len(pending), desc="Traduzindo", unit="item", ncols=80) as pbar:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {
                ex.submit(process_batch, b, system_prompt, args.model, args.temperature, args.dry_run): (i+1, b)
                for i,b in enumerate(batches)
            }

            for future in concurrent.futures.as_completed(futures):
                batch_idx, batch = futures[future]
                try:
                    result = future.result()
                    if result:
                        translated.update(result)
                        success += len(result)
                        pbar.update(len(result))

                        # Collect original->translated pairs for auto-extraction
                        if extraction_engine:
                            for key, item in batch:
                                if key in result:
                                    orig = item.get("Text", "")
                                    pt = result[key].get("Text", "")
                                    if orig and pt and orig != pt:
                                        recent_pairs.append((orig, pt))
                                        # Avoid unbounded memory growth
                                        if len(recent_pairs) > 500:
                                            recent_pairs = recent_pairs[-250:]
                    else:
                        # Fallback individual
                        failed += len(batch)
                        for key, item in batch:
                            translated[key] = {"Offset": item.get("Offset",0), "Text": item.get("Text",""), "_failed": True}
                        pbar.update(len(batch))

                    batches_done += 1

                    # Auto-extract terms every N batches
                    if extraction_engine and batches_done % args.extract_every == 0 and recent_pairs:
                        pair_count = len(recent_pairs)
                        try:
                            logger.info(f"[AUTO-EXTRACT] Ciclo no batch {batch_idx}: {pair_count} pares acumulados.")
                            added = glossary.extract_terms_from_pairs(recent_pairs, engine=extraction_engine, max_terms=15)
                            if added:
                                glossary.save()
                                logger.info(f"[AUTO-EXTRACT] +{added} termos adicionados ao glossario (total: {len(glossary.entries)}).")
                            else:
                                logger.info(f"[AUTO-EXTRACT] Nenhum termo novo adicionado neste ciclo.")
                            recent_pairs = []
                        except Exception as e:
                            logger.warning(f"[AUTO-EXTRACT] falhou no batch {batch_idx}: {e}")
                            recent_pairs = []

                    # Salva progresso (not every batch — profile save_every)
                    if batches_done % max(1, profile_save_every) == 0 or batches_done == len(batches):
                        output_data["strings"] = translated
                        atomic_save(output_data, args.output)

                except Exception as e:
                    logger.error(f"Batch {batch_idx}: {e}")
                    failed += len(batch)
                    pbar.update(len(batch))
    
    # ── FINALIZA ──
    glossary.save()
    output_data["strings"] = translated
    atomic_save(output_data, args.output)

    # Grava mapeamento de UUIDs preservados para segunda passada localizada
    if args.mode == "preserve" and preserve_map:
        try:
            atomic_save(preserve_map, args.preserve_map)
            logger.info(f"🗺️  Preserve map salvo: {args.preserve_map} ({len(preserve_map)} UUIDs)")
        except Exception as e:
            logger.warning(f"Não foi possível salvar preserve_map: {e}")

    logger.info(
        f"[OK] Concluído: {success} traduzidos | {failed} falhas | "
        f"{preserved_exact} exact EN | {preserved_inline} inline locked"
    )
    logger.info(f"📁 Salvo: {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
