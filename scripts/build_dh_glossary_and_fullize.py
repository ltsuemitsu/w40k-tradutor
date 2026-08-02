#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Lean DH glossary (high-value only) + fullize.

Caps actionable EN→PT pairs so fullize regex stays fast (~400–800 terms).
Priority: RT selective hits in DH corpus, then frequent short labels from preserved.
"""
from __future__ import annotations

import re
import shutil
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tradutor import SmartGlossary, atomic_save, fullize_file, fullize_text, load_json
from w40k_project import load_localization
import w40k_glossary as gl

DH = Path(r"D:/Translator40k/DarkHeresy")
EN_PATH = DH / "input" / "enGB_1.json"
PRES_PATH = DH / "output" / "ptBR_preserved_1.json"
FULL_PATH = DH / "output" / "ptBR_full_1.json"
GLOSS_PATH = DH / "glossary.json"
RT_GLOSS = Path(r"D:/app_w40k_tradutor/glossary.json")

MAX_TERMS = 600

BLOCK_SINGLE = {
    "lord", "lady", "master", "order", "house", "power", "force", "fire",
    "blood", "death", "light", "dark", "human", "turn", "round", "test",
    "check", "save", "open", "close", "back", "next", "start", "end",
    "level", "type", "area", "item", "quest", "skill", "ability", "damage",
    "attack", "bonus", "move", "ship", "void", "warp", "flash", "blaster",
    "none", "null", "yes", "no", "ok", "true", "false", "defend",
}


def text_of(e) -> str:
    return (e.get("Text") or "") if isinstance(e, dict) else ""


def is_clean_term(en: str) -> bool:
    en = en.strip()
    if len(en) < 4 or len(en) > 48:
        return False
    if en.lower() in BLOCK_SINGLE:
        return False
    if en[0] in "\"'“”([{<":
        return False
    if en.startswith("("):
        return False
    if any(ch in en for ch in ".?!\n;"):
        return False
    if en.count(":") > 1:
        return False
    if en.count(" ") > 4:
        return False
    if not re.search(r"[A-Za-z]", en):
        return False
    words = re.findall(r"[A-Za-z][A-Za-z'&\-]*", en)
    if not words:
        return False
    titled = sum(1 for w in words if w[0].isupper() or w.isupper())
    if titled < max(1, (len(words) + 1) // 2):
        return False
    return True


def main() -> None:
    print("Load…")
    en_s = load_localization(EN_PATH)["strings"]
    pt_s = load_localization(PRES_PATH)["strings"]
    all_en = [text_of(v) for v in en_s.values() if text_of(v).strip()]
    joined_l = "\n".join(all_en).lower()

    scored: list[tuple[int, dict]] = []  # (score, entry)

    def consider(en: str, pt: str, source: str, category: str, base: int) -> None:
        en, pt = en.strip(), pt.strip()
        if not en or not pt or en == pt:
            return
        if not is_clean_term(en):
            return
        if len(pt) > 80 or "\n" in pt:
            return
        cnt = joined_l.count(en.lower())
        if cnt < 1:
            return
        # score: frequency * length bias (prefer multiword names)
        score = base + cnt * 3 + len(en.split()) * 5 + min(len(en), 30)
        scored.append((score, {
            "term_english": en,
            "term_translated": pt,
            "category": category or "other",
            "preserve": False,
            "inline": False,
            "source": source,
            "confidence": "medium",
            "context": "",
            "usage_count": cnt,
        }))

    # RT first (high base score)
    rt = load_json(str(RT_GLOSS)) or {}
    for t in rt.get("terms") or []:
        if not isinstance(t, dict):
            continue
        consider(
            str(t.get("term_english") or ""),
            str(t.get("term_translated") or ""),
            "rt_selective",
            str(t.get("category") or "other"),
            base=1000,
        )

    # preserved exact labels
    for k, ev in en_s.items():
        consider(
            text_of(ev),
            text_of(pt_s.get(k, {})),
            "preserved_exact",
            gl.guess_category(text_of(ev), []),
            base=100,
        )

    # dedupe by EN lower keeping highest score
    best: dict[str, tuple[int, dict]] = {}
    for score, entry in scored:
        key = entry["term_english"].lower()
        if key not in best or score > best[key][0]:
            best[key] = (score, entry)

    ranked = sorted(best.values(), key=lambda x: -x[0])
    # drop singles in block
    picked = []
    for score, entry in ranked:
        en = entry["term_english"]
        if " " not in en and en.lower() in BLOCK_SINGLE:
            continue
        picked.append(entry)
        if len(picked) >= MAX_TERMS:
            break

    print("picked", len(picked), "of", len(best), "unique candidates")

    # longest-first in file helps humans; fullize sorts again
    term_list = sorted(picked, key=lambda t: (-len(t["term_english"]),
                                              t["term_english"].lower()))
    gloss = {
        "metadata": {
            "version": "1.2",
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "total_terms": len(term_list),
            "name": "Dark Heresy — fullize lean",
            "game": "dark_heresy",
            "game_version": "1",
            "kind": "base_game",
            "max_terms": MAX_TERMS,
            "sources": ["rt_selective", "preserved_exact"],
        },
        "terms": term_list,
    }
    bak = DH / "backups" / f"glossary_lean_{datetime.now():%Y%m%d_%H%M%S}.json"
    bak.parent.mkdir(parents=True, exist_ok=True)
    if GLOSS_PATH.is_file():
        bak.write_bytes(GLOSS_PATH.read_bytes())
    atomic_save(gloss, str(GLOSS_PATH))
    print("glossary", GLOSS_PATH)

    g = SmartGlossary(str(GLOSS_PATH))
    m = g.en_to_pt_map()
    print("map", len(m))
    for en, pt in list(m.items())[:25]:
        print(f"  {en!r} → {pt!r}")

    print("Fullize…")
    shutil.copy2(PRES_PATH, FULL_PATH)
    # efficiency: call fullize_text with map once compiled via fullize_file
    rc = fullize_file(str(PRES_PATH), str(FULL_PATH), str(GLOSS_PATH))
    print("rc", rc)

    pres = load_localization(PRES_PATH)["strings"]
    full = load_localization(FULL_PATH)["strings"]
    same = diff = flagged = 0
    samples = []
    for k, ev in en_s.items():
        if not text_of(ev).strip():
            continue
        p, f = text_of(pres.get(k, {})), text_of(full.get(k, {}))
        if p == f:
            same += 1
        else:
            diff += 1
            if len(samples) < 22:
                samples.append((text_of(ev)[:50], p[:55], f[:55]))
        if isinstance(full.get(k), dict) and full[k].get("_fullized"):
            flagged += 1
    print(f"same={same} diff={diff} _fullized={flagged}")
    for et, p, f in samples:
        print(" EN", repr(et))
        print(" PR", repr(p))
        print(" FU", repr(f))

    # spot-check a few known terms still EN in preserved
    checks = ["Bolter", "Heavy Bolter", "Flashbang", "Rogue Trader", "Lord Captain",
              "Ballistic Skill", "Weapon Skill", "Adeptus Mechanicus"]
    print("spot checks in FULL (first 3 hits each):")
    for term in checks:
        hits = 0
        for e in full.values():
            t = text_of(e)
            if term in t:
                # show if still EN form present
                hits += 1
                if hits <= 1:
                    print(f"  still has {term!r}? yes example… {t[:80]!r}")
        if hits == 0:
            print(f"  {term!r}: no longer present as EN substring (or rare)")

    try:
        import w40k_project as wp
        proj = wp.Project.open(DH)
        proj.set_track_file(wp.TRACK_FULL, FULL_PATH)
        proj.update_track(wp.TRACK_FULL, wp.TRACK_STATUS_DONE,
                          translated=len(full), skipped_free=0)
        proj.state["glossary_stamp"] = {
            "terms": len(term_list),
            "built_for": "dark_heresy",
            "name": gloss["metadata"]["name"],
            "kind": "base_game",
            "mod_name": None,
            "parent": None,
        }
        proj.save()
        print("project.json ok")
    except Exception as exc:
        print("project", exc)


if __name__ == "__main__":
    main()
