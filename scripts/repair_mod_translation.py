#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Repair shipped PT masters: gender {mf|…} sides + leaked §TERM placeholders.

Usage:
  python scripts/repair_mod_translation.py \\
    --pt "data/MOD/enGB preserved.json" \\
    --out "data/MOD/enGB preserved.repaired.json" \\
    [--preserve-map preserve_map.json] \\
    [--en data/en/enGB_new.json]

Safe: writes a new file (or --in-place with .bak).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tradutor import localize_gender_tags, scrub_leaked_term_placeholders  # noqa: E402


TERM_RE = re.compile(r"§TERM(\d+)§|\$TERM(\d+)\$|\[\[W40KT(\d+)\]\]")


def load_strings(path: str) -> dict:
    data = json.load(open(path, encoding="utf-8"))
    if "strings" not in data:
        raise SystemExit(f"No strings key in {path}")
    return data


def try_restore_terms(text: str, terms: list) -> str:
    """If placeholders remain and we know terms, fill by index then scrub rest."""
    if not TERM_RE.search(text):
        return text
    terms = [t for t in (terms or []) if t and t != "prescan_cache"]
    if not terms:
        return scrub_leaked_term_placeholders(text)

    def repl(m: re.Match) -> str:
        raw = m.group(1) or m.group(2) or m.group(3)
        i = int(raw)
        if 0 <= i < len(terms):
            return terms[i]
        # common LLM off-by-one: TERM2 with only 1 term
        if terms:
            return terms[min(i, len(terms) - 1)]
        return ""

    text = TERM_RE.sub(repl, text)
    return scrub_leaked_term_placeholders(text)


def repair_file(pt_path: str, out_path: str, preserve_map_path: str | None, en_path: str | None) -> None:
    data = load_strings(pt_path)
    strings = data["strings"]

    pmap = {}
    if preserve_map_path and os.path.exists(preserve_map_path):
        pmap = json.load(open(preserve_map_path, encoding="utf-8"))

    en_strings = {}
    if en_path and os.path.exists(en_path):
        en_strings = json.load(open(en_path, encoding="utf-8")).get("strings") or {}

    n_mf = n_term = n_changed = 0
    for key, val in strings.items():
        if not isinstance(val, dict):
            continue
        text = val.get("Text") or ""
        orig = text

        # Gender tags
        if "{mf|" in text or "{rt_mf|" in text or "{MF|" in text:
            new_t = localize_gender_tags(text)
            if new_t != text:
                n_mf += 1
                text = new_t

        # Leaked term locks
        if TERM_RE.search(text):
            terms = []
            entry = pmap.get(key)
            if isinstance(entry, dict):
                terms = list(entry.get("terms") or [])
            elif isinstance(entry, list):
                terms = entry
            # fallback: if single placeholder and EN exact known from en file — skip
            text2 = try_restore_terms(text, terms)
            if text2 != text:
                n_term += 1
                text = text2
            elif TERM_RE.search(text):
                text = scrub_leaked_term_placeholders(text)
                n_term += 1

        if text != orig:
            val["Text"] = text
            n_changed += 1

    os.makedirs(os.path.dirname(os.path.abspath(out_path)) or ".", exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    print(f"Wrote {out_path}")
    print(f"  strings changed: {n_changed}")
    print(f"  gender mf fixes: {n_mf}")
    print(f"  term placeholder fixes: {n_term}")


def main():
    ap = argparse.ArgumentParser(description="Repair mf gender tags + leaked TERM placeholders")
    ap.add_argument("--pt", required=True, help="PT JSON (MOD master)")
    ap.add_argument("--out", help="Output path (default: *.repaired.json)")
    ap.add_argument("--in-place", action="store_true", help="Overwrite --pt (writes .bak first)")
    ap.add_argument("--preserve-map", default="preserve_map.json")
    ap.add_argument("--en", default="", help="Optional EN source for future heuristics")
    args = ap.parse_args()

    pt = args.pt
    if args.in_place:
        bak = pt + ".bak"
        shutil.copy2(pt, bak)
        print(f"Backup: {bak}")
        out = pt
    else:
        out = args.out or re.sub(r"\.json$", ".repaired.json", pt, flags=re.I)
        if out == pt:
            out = pt + ".repaired.json"

    repair_file(pt, out, args.preserve_map, args.en or None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
