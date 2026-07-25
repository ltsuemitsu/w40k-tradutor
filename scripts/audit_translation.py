#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Audit PT translation masters for failures, untranslated, and half-PT strings.

Finds three classes of problems:
  1. _failed   — API errors (still raw EN)
  2. identical — PT == EN source, not flagged preserve (some are correct: names/EULA)
  3. suspect   — half-translated: PT text with leftover EN articles/prepositions

Usage:
  python scripts/audit_translation.py --pt "data/MOD/enGB preserved.json" \\
    --en data/en/enGB_new.json [--out audit_report.json]

  # Re-translate only the flagged UUIDs:
  python scripts/audit_translation.py --pt "..." --en "..." --export-uuids retry_uuids.json
  python tradutor.py -i data/en/enGB_new.json -o "..." -g glossary.json \\
    --mode preserve --resume --retranslate-map retry_uuids.json --model deepseek-v4-flash
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Common EN function words that should NOT appear in finished PT
_EN_INDICATORS = re.compile(
    r'\b('
    r'the|and|you|with|this|that|have|from|they|your|was|were|been|will|'
    r'would|could|should|about|which|their|what|when|where|while|after|'
    r'before|between|through|during|against|without|within|along|across|'
    r'because|unless|although|however|therefore|moreover'
    r')\b',
    re.I,
)

# PT characters that signal real translation happened
_PT_CHARS = set("ãáàâéêíóôúçÃÁÀÂÉÊÍÓÔÚÇñÑ")

# Terms that are legitimately EN even in PT (proper names, tech)
_LEGIT_EN_IDENTICAL = {
    "Audiokinetic Inc.", "Unity Technologies", "Syrinscape Pty Ltd.",
    "Dungeon Architect",
}


def audit_strings(pt_data: dict, en_data: dict) -> dict:
    pt = pt_data.get("strings") or {}
    en = en_data.get("strings") or {}

    failed = []
    identical = []
    suspect = []
    stats = Counter()

    for key, val in pt.items():
        if not isinstance(val, dict):
            stats["bad_value"] += 1
            continue

        text = (val.get("Text") or "").strip()
        orig = (en.get(key, {}).get("Text") or "").strip()
        stats["total"] += 1

        if val.get("_failed"):
            failed.append({"uuid": key, "text": text[:120], "reason": "api_error"})
            stats["failed"] += 1
            continue

        if val.get("_skipped") or val.get("_preserved"):
            stats["skipped_or_preserved"] += 1
            continue

        # identical to EN (and long enough to matter)
        if text == orig and len(text) > 10:
            if text in _LEGIT_EN_IDENTICAL:
                stats["legit_identical"] += 1
                continue
            failed.append({"uuid": key, "text": text[:120], "reason": "identical_to_en"})
            stats["identical"] += 1
            continue

        # suspicious: looks half-PT, half-EN
        if len(text) > 15:
            has_pt = bool(_PT_CHARS & set(text))
            en_hits = len(_EN_INDICATORS.findall(text))
            if has_pt and en_hits >= 2:
                suspect.append({
                    "uuid": key,
                    "text": text[:160],
                    "en_hits": en_hits,
                    "reason": "half_translated",
                })
                stats["suspect"] += 1
            elif not has_pt and en_hits >= 3 and not text.startswith("{") and not text.startswith("<"):
                # fully EN-looking but wasn't caught above
                suspect.append({
                    "uuid": key,
                    "text": text[:160],
                    "en_hits": en_hits,
                    "reason": "looks_untranslated",
                })
                stats["suspect"] += 1

    return {
        "stats": dict(stats),
        "failed": failed,
        "identical": identical,
        "suspect": suspect,
        "all_fix_uuids": sorted(
            {x["uuid"] for x in failed} | {x["uuid"] for x in identical} | {x["uuid"] for x in suspect}
        ),
    }


def main():
    ap = argparse.ArgumentParser(description="Audit PT translation for failures and quality")
    ap.add_argument("--pt", required=True, help="PT JSON to audit")
    ap.add_argument("--en", required=True, help="EN source JSON")
    ap.add_argument("--out", default="", help="Write report JSON")
    ap.add_argument("--export-uuids", default="", help="Write UUID list for --retranslate-map")
    args = ap.parse_args()

    pt_data = json.load(open(args.pt, encoding="utf-8"))
    en_data = json.load(open(args.en, encoding="utf-8"))

    report = audit_strings(pt_data, en_data)
    stats = report["stats"]

    print(f"=== AUDIT: {args.pt} ===")
    print(f"Total strings:        {stats.get('total', 0):,}")
    print(f"  _failed (API):      {stats.get('failed', 0)}")
    print(f"  identical to EN:    {stats.get('identical', 0)}")
    print(f"  suspect quality:    {stats.get('suspect', 0)}")
    print(f"  skipped/preserved:  {stats.get('skipped_or_preserved', 0)}")
    print(f"  legit identical:    {stats.get('legit_identical', 0)}")
    print(f"\nTotal to fix: {len(report['all_fix_uuids'])}")

    if report["suspect"]:
        print(f"\n--- Top suspect samples ---")
        for s in sorted(report["suspect"], key=lambda x: -x["en_hits"])[:15]:
            print(f"  [{s['en_hits']} EN] {s['uuid'][:12]}: {s['text'][:100]}")

    if report["failed"]:
        print(f"\n--- _failed samples ---")
        for f in report["failed"][:10]:
            print(f"  {f['uuid'][:12]}: {f['text']}")

    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\nReport: {args.out}")

    if args.export_uuids:
        uuids = report["all_fix_uuids"]
        with open(args.export_uuids, "w", encoding="utf-8") as f:
            json.dump(uuids, f, indent=2)
        print(f"UUIDs to retry: {args.export_uuids} ({len(uuids)} entries)")
        print(f"\nRe-translate command:")
        print(
            f'  python tradutor.py -i "{args.en}" -o "{args.pt}" '
            f'-g glossary.json --mode preserve --resume '
            f'--retranslate-map "{args.export_uuids}" --model deepseek-v4-flash'
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
