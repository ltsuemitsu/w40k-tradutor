#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Wiki Sync — Sincroniza glossario com dados da WH40K Rogue Trader Wiki
============================================================================
Fonte: https://roguetrader.wh40k.wiki/
Dados offline: data/glossaries/wiki_terms.json (~2694 termos, 16 categorias)

Uso:
    python wiki_sync.py --glossary glossary.json --sync
    python wiki_sync.py --glossary glossary.json --sync --review
    python wiki_sync.py --glossary glossary.json --stats
    python wiki_sync.py --glossary glossary.json --export-csv terms.csv
"""

import json
import os
import sys
import argparse
from typing import Dict, List, Optional
from datetime import datetime

_BASE_DIR = os.path.dirname(os.path.abspath(__file__))
_DEFAULT_WIKI_JSON = os.path.join(_BASE_DIR, "data", "glossaries", "wiki_terms.json")


def load_json(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(data: dict, path: str):
    os.makedirs(os.path.dirname(path) if os.path.dirname(path) else ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def get_wiki_data(path: Optional[str] = None) -> Dict[str, List[str]]:
    """Load offline wiki term lists from JSON (default: data/glossaries/wiki_terms.json)."""
    wiki_path = path or _DEFAULT_WIKI_JSON
    if not os.path.exists(wiki_path):
        raise FileNotFoundError(
            f"Wiki terms file not found: {wiki_path}\n"
            "Expected data/glossaries/wiki_terms.json next to wiki_sync.py."
        )
    raw = load_json(wiki_path)
    # Accept either {"categories": {...}} or a bare {cat: [terms...]} map
    cats = raw.get("categories", raw)
    if not isinstance(cats, dict):
        raise ValueError(f"Invalid wiki terms format in {wiki_path}")
    return {str(k): list(v) for k, v in cats.items() if isinstance(v, list)}


def sync_glossary(glossary_path: str, review: bool = False,
                  only_cats: Optional[List[str]] = None) -> int:
    """Sincroniza glossario com dados da wiki."""
    wiki = get_wiki_data()

    if os.path.exists(glossary_path):
        data = load_json(glossary_path)
    else:
        data = {"metadata": {"version": "2.0", "created_at": datetime.now().isoformat()}, "terms": []}

    existing = {t["term_english"].lower() for t in data.get("terms", [])}
    added = 0
    candidates = []

    for category, names in wiki.items():
        if only_cats and category not in only_cats:
            continue
        for name in names:
            key = name.lower()
            if key in existing:
                continue
            candidates.append({
                "term_english": name,
                "term_translated": name,
                "category": category,
                "source": "wh40k_wiki",
                "context": f"WH40K Wiki — {category}",
                "confidence": "high",
                "first_seen_batch": 0,
                "usage_count": 1,
                "created_at": datetime.now().isoformat(),
                "preserve": True,
            })

    if review and candidates:
        print(f"\n{len(candidates)} novos termos da wiki para adicionar:\n")
        approved = []
        for c in candidates:
            print(f'  "{c["term_english"]}" [{c["category"]}]')
            resp = input("  Adicionar? [Y/n/q]: ").strip().lower()
            if resp == "q":
                break
            if resp in ("y", ""):
                approved.append(c)
        candidates = approved

    for c in candidates:
        data["terms"].append(c)
        existing.add(c["term_english"].lower())
        added += 1

    data.setdefault("metadata", {})
    data["metadata"]["updated_at"] = datetime.now().isoformat()
    data["metadata"]["total_terms"] = len(data["terms"])
    data["metadata"]["wiki_source"] = "https://roguetrader.wh40k.wiki/"
    save_json(data, glossary_path)

    return added


def export_csv(glossary_path: str, csv_path: str):
    """Exporta glossario para CSV."""
    import csv
    data = load_json(glossary_path)
    with open(csv_path, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["term_english", "term_translated", "category", "preserve", "context", "confidence"])
        for t in data.get("terms", []):
            w.writerow([
                t.get("term_english", ""), t.get("term_translated", ""),
                t.get("category", ""), t.get("preserve", False),
                t.get("context", ""), t.get("confidence", ""),
            ])
    print(f"Exportado: {csv_path}")


def show_stats(glossary_path: str):
    """Mostra estatisticas do glossario."""
    data = load_json(glossary_path)
    terms = data.get("terms", [])

    by_cat = {}
    preserved = 0
    for t in terms:
        cat = t.get("category", "sem_categoria")
        by_cat[cat] = by_cat.get(cat, 0) + 1
        if t.get("preserve"):
            preserved += 1

    print(f"\n{'=' * 50}")
    print(f"  GLOSSARIO: {glossary_path}")
    print(f"{'=' * 50}")
    print(f"  Total: {len(terms)} termos")
    print(f"  A preservar: {preserved}")
    print(f"  Para consistencia: {len(terms) - preserved}")
    print()
    for cat, count in sorted(by_cat.items(), key=lambda x: -x[1]):
        print(f"  {cat}: {count}")
    print(f"{'=' * 50}")


def main():
    parser = argparse.ArgumentParser(description="Wiki Sync — Atualiza glossario com dados da wiki")
    parser.add_argument("--glossary", required=True, help="Arquivo JSON do glossario")
    parser.add_argument("--sync", action="store_true", help="Sincroniza com dados da wiki")
    parser.add_argument("--review", action="store_true", help="Revisa antes de adicionar")
    parser.add_argument("--export-csv", help="Exporta para CSV")
    parser.add_argument("--stats", action="store_true", help="Mostra estatisticas")
    parser.add_argument("--only", help="Sincronizar apenas categorias especificas (virgula)")
    args = parser.parse_args()

    only_cats = None
    if args.only:
        only_cats = [c.strip() for c in args.only.split(",")]

    if args.sync:
        added = sync_glossary(args.glossary, args.review, only_cats)
        print(f"\nSincronizado: {added} novos termos adicionados ao glossario")

    if args.export_csv:
        export_csv(args.glossary, args.export_csv)

    if args.stats:
        show_stats(args.glossary)

    if not any([args.sync, args.export_csv, args.stats]):
        print("Use --sync, --export-csv ou --stats")


if __name__ == "__main__":
    main()
