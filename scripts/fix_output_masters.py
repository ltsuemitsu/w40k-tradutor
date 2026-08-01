#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Fix shipped PT masters in a RogueTrader project folder.

1) Scrub/repair hallucinated §TAG/§TERM locks (using EN + preserve_map)
2) Re-run fullize with parenthesis-safe glossary replace
   (fixes 'Base Skill: Lore (Imperium)' etc.)

Usage:
  python scripts/fix_output_masters.py \\
    --project D:/Translator40k/RogueTrader \\
    --glossary glossary.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tradutor import (  # noqa: E402
    SmartGlossary,
    TagProtector,
    TermProtector,
    fullize_text,
    localize_gender_tags,
    load_json,
    atomic_save,
)


def scrub_locks(text: str) -> str:
    """Remove leftover / hallucinated lock tokens (conservative)."""
    if not text:
        return text
    # §TAG3$ glued dollar
    text = re.sub(r"§TAG(\d+)\$", lambda m: "§TAG%s§" % m.group(1), text, flags=re.I)
    text = re.sub(r"§TERM(\d+)\$", lambda m: "§TERM%s§" % m.group(1), text, flags=re.I)
    # paired wrappers around real words
    text = re.sub(
        r"(?:\[\[W40KG\d+\]\]|§TAG\d+§|\$TAG\d+\$)"
        r"([^\[\]§$]{1,80}?)"
        r"(?:\[\[W40KG\d+\]\]|§TAG\d+§|\$TAG\d+\$)",
        lambda m: m.group(1),
        text,
        flags=re.I,
    )
    # bare + mangles §TAG24%% §TAG12® §TERM1°
    text = re.sub(
        r"\[\[W40KT\d+\]\]|\[\[W40KG\d+\]\]"
        r"|§TERM\d+§|\$TERM\d+\$"
        r"|§TAG\d+§|\$TAG\d+\$"
        r"|§(?:TAG|TERM)\d+(?:§|\$|°|®|%)*"
        r"|\$(?:TAG|TERM)\d+(?:§|\$|°|®|%)*",
        "",
        text,
        flags=re.I,
    )
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text


_STOP = {"the", "and", "for", "your", "you", "a", "an", "of", "to", "as", "is", "in", "on"}


def repair_locks(en_text: str, pt_text: str, terms: Optional[List[str]] = None) -> str:
    if not pt_text:
        return pt_text
    out = pt_text

    # restore real markup from EN protect map when possible
    if en_text:
        _, tag_ph = TagProtector.protect(en_text)
        if tag_ph and re.search(r"§TAG\d+|\[\[W40KG", out, re.I):
            out = TagProtector.restore(out, tag_ph)

    terms = [t for t in (terms or []) if t and t != "prescan_cache"]
    if terms and re.search(r"W40KT|§TERM|\$TERM", out, re.I):
        ph = {TermProtector._ph_token(i): t for i, t in enumerate(terms)}
        for i, t in enumerate(terms):
            ph["§TERM%d§" % i] = t
            ph["$TERM%d$" % i] = t
        out = TermProtector.restore(out, ph)

    # unwrap pairs before bare fill
    out = re.sub(
        r"(?:\[\[W40KG\d+\]\]|§TAG\d+§|\$TAG\d+\$)"
        r"([^\[\]§$]{1,80}?)"
        r"(?:\[\[W40KG\d+\]\]|§TAG\d+§|\$TAG\d+\$)",
        lambda m: m.group(1),
        out,
        flags=re.I,
    )

    if terms and re.search(r"§TAG\d+|\[\[W40KG", out, re.I):
        fill = []
        seen = set()
        for t in terms:
            if len(t) < 3 or t.lower() in _STOP:
                continue
            tl = t.lower()
            if tl in seen:
                continue
            seen.add(tl)
            if en_text and not re.search(r"\b" + re.escape(t) + r"\b", en_text, re.I):
                continue
            if re.search(r"\b" + re.escape(t) + r"\b", out, re.I):
                continue
            fill.append(t)
        if fill:
            idx = 0

            def _fill(m: re.Match) -> str:
                nonlocal idx
                if idx < len(fill):
                    v = fill[idx]
                    idx += 1
                    return v
                return m.group(0)

            out = re.sub(r"§TAG\d+§|\[\[W40KG\d+\]\]|§TAG\d+", _fill, out, flags=re.I)

    out = scrub_locks(out)
    if "{mf|" in out.lower() or "{rt_mf|" in out.lower():
        out = localize_gender_tags(out)
    return out


def fullize_text_safe(text: str, en_to_pt: Dict[str, str]) -> str:
    """Delegate to engine fullize_text (parenthesis-safe)."""
    return fullize_text(text, en_to_pt)


LEAK_RE = re.compile(r"§(?:TAG|TERM)\d+|\[\[W40K[GT]\d+\]\]|\$(?:TAG|TERM)\d+", re.I)


def process_file(
    pt_path: Path,
    out_path: Path,
    en_strings: dict,
    pmap: dict,
    en_to_pt: Dict[str, str],
    do_fullize: bool,
) -> dict:
    data = load_json(str(pt_path))
    strings = data["strings"]
    n_lock = n_full = n_mf = n_changed = 0

    for key, val in strings.items():
        if not isinstance(val, dict):
            continue
        text = val.get("Text") or ""
        orig = text

        en_text = ""
        en_e = en_strings.get(key)
        if isinstance(en_e, dict):
            en_text = en_e.get("Text") or ""
        elif isinstance(en_e, str):
            en_text = en_e

        terms: List[str] = []
        entry = pmap.get(key)
        if isinstance(entry, dict):
            terms = list(entry.get("terms") or [])
        elif isinstance(entry, list):
            terms = entry

        if LEAK_RE.search(text):
            text2 = repair_locks(en_text, text, terms)
            if text2 != text:
                n_lock += 1
                text = text2

        if "{mf|" in text or "{rt_mf|" in text:
            t3 = localize_gender_tags(text)
            if t3 != text:
                n_mf += 1
                text = t3

        if do_fullize:
            t4 = fullize_text_safe(text, en_to_pt)
            if t4 != text:
                n_full += 1
                text = t4
                val.pop("_preserved", None)
                val["_fullized"] = True

        if text != orig:
            val["Text"] = text
            n_changed += 1

    atomic_save(data, str(out_path))
    residual = sum(
        1
        for v in strings.values()
        if isinstance(v, dict) and LEAK_RE.search(v.get("Text") or "")
    )
    base_left = [
        v.get("Text")
        for v in strings.values()
        if isinstance(v, dict) and str(v.get("Text") or "").startswith("Base Skill:")
    ]
    return {
        "changed": n_changed,
        "locks": n_lock,
        "fullize": n_full,
        "mf": n_mf,
        "residual_leaks": residual,
        "base_skill_left": base_left,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", required=True, help="RogueTrader project folder")
    ap.add_argument("--glossary", default=str(ROOT / "glossary.json"))
    ap.add_argument("--in-place", action="store_true", help="Overwrite masters (writes .bak)")
    args = ap.parse_args()

    proj = Path(args.project)
    out_dir = proj / "output"
    en_path = proj / "input" / "enGB_1.6.1.514.json"
    if not en_path.is_file():
        en_path = proj / "input" / "enGB.json"
    pmap_path = proj / "patches" / "preserve_map.json"

    preserved = out_dir / "ptBR_preserved_1.6.1.514.json"
    full = out_dir / "ptBR_full_1.6.1.514.json"
    if not preserved.is_file():
        # fallback any preserved
        cands = sorted(out_dir.glob("ptBR_preserved*.json"))
        if not cands:
            raise SystemExit(f"No preserved master in {out_dir}")
        preserved = cands[-1]
    if not full.is_file():
        cands = sorted(out_dir.glob("ptBR_full*.json"))
        full = cands[-1] if cands else out_dir / preserved.name.replace("preserved", "full")

    en_data = load_json(str(en_path)) if en_path.is_file() else {}
    en_strings = en_data.get("strings") or en_data
    pmap = {}
    if pmap_path.is_file():
        pmap = json.loads(pmap_path.read_text(encoding="utf-8"))

    gloss = SmartGlossary(args.glossary, preserve_mode="preserve")
    en_to_pt = gloss.en_to_pt_map()
    print(f"EN: {en_path} ({len(en_strings)} strings)")
    print(f"Glossary pairs: {len(en_to_pt)}")
    print(f"preserve_map: {len(pmap)} entries")

    # 1) repair preserved (locks only — keep exact EN for preserve track)
    if args.in_place:
        bak = preserved.with_suffix(preserved.suffix + ".bak")
        shutil.copy2(preserved, bak)
        print(f"Backup: {bak}")
        p_out = preserved
    else:
        p_out = preserved.with_name(preserved.stem + ".fixed.json")
    stats_p = process_file(preserved, p_out, en_strings, pmap, en_to_pt, do_fullize=False)
    print(f"Preserved → {p_out}")
    print(f"  {stats_p}")

    # 2) full = start from repaired preserved, fullize everything
    # Prefer re-derive full from repaired preserved for consistency
    src_for_full = p_out
    if args.in_place:
        bakf = full.with_suffix(full.suffix + ".bak")
        if full.is_file():
            shutil.copy2(full, bakf)
            print(f"Backup: {bakf}")
        f_out = full
    else:
        f_out = full.with_name(full.stem + ".fixed.json") if full.is_file() else out_dir / "ptBR_full.fixed.json"

    stats_f = process_file(src_for_full, f_out, en_strings, pmap, en_to_pt, do_fullize=True)
    print(f"Full → {f_out}")
    print(f"  {stats_f}")
    if stats_f["base_skill_left"]:
        print("  WARNING Base Skill still EN:")
        for s in stats_f["base_skill_left"]:
            print("   ", s)
    else:
        print("  All Base Skill:* translated (or absent).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
