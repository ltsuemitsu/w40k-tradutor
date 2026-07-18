# -*- coding: utf-8 -*-
"""Tests for tradutor.py — core engine pieces that never touch the LLM.

Covered: TagProtector, SmartGlossary, split_batch, load_blacklist, atomic_save.
All fixtures are tiny synthetic JSONs built in temp dirs. No network, no API keys.
"""
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tradutor import (
    SmartGlossary,
    TagProtector,
    atomic_save,
    estimate_tokens,
    load_blacklist,
    split_batch,
)


def _term(en, pt, category, preserve):
    return {
        "term_english": en,
        "term_translated": pt,
        "category": category,
        "preserve": preserve,
        "source": "test",
        "context": "",
        "confidence": "high",
        "usage_count": 1,
        "created_at": "2026-01-01T00:00:00",
    }


GLOSSARY_DATA = {
    "metadata": {"version": "2.1", "total_terms": 4},
    "terms": [
        _term("Plasma Gun", "Plasma Gun", "item", True),        # preserve flag
        _term("Power Sword", "Power Sword", "weapon", False),   # preserve category
        _term("Med Kit", "Med Kit", "item", True),              # space in term
        _term("Imperial Navy", "Marinha Imperial", "faction", False),  # not preserved
    ],
}


class TestTagProtector(unittest.TestCase):
    TAGGED = (
        'You gain {g|talent}Barrage{/g} and {n}move{/n} faster. '
        '<color=#ff0000>Red warning</color> with <sprite=icon_skull> icon '
        'and <link=talent_01>link text</link>.'
    )

    def test_round_trip_is_faithful(self):
        protected, ph = TagProtector.protect(self.TAGGED)
        restored = TagProtector.restore(protected, ph)
        self.assertEqual(restored, self.TAGGED)

    def test_protect_shields_all_tag_kinds(self):
        protected, ph = TagProtector.protect(self.TAGGED)
        for fragment in ("{g|", "{/g}", "{n}", "{/n}", "<color", "</color>",
                         "<sprite", "<link", "</link>"):
            self.assertNotIn(fragment, protected)
        # Placeholders stand in for the tags
        self.assertTrue(re.findall(r"§TAG\d+§", protected))
        # Inner text stays visible for the translator
        for inner in ("Barrage", "move", "Red warning", "link text"):
            self.assertIn(inner, protected)

    def test_restore_leaves_no_placeholders(self):
        protected, ph = TagProtector.protect(self.TAGGED)
        restored = TagProtector.restore(protected, ph)
        self.assertIsNone(re.search(r"§TAG\d+§", restored))

    def test_plain_text_is_untouched(self):
        text = "Nothing to protect here."
        protected, ph = TagProtector.protect(text)
        self.assertEqual(protected, text)
        self.assertEqual(ph, {})
        self.assertEqual(TagProtector.restore(protected, ph), text)

    def test_empty_text(self):
        protected, ph = TagProtector.protect("")
        self.assertEqual(protected, "")
        self.assertEqual(ph, {})


class TestSmartGlossary(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.glossary_path = os.path.join(self._tmp.name, "glossary.json")
        with open(self.glossary_path, "w", encoding="utf-8") as f:
            json.dump(GLOSSARY_DATA, f, ensure_ascii=False)

    def _make(self, mode="preserve"):
        return SmartGlossary(self.glossary_path, preserve_mode=mode)

    def test_preserve_flagged_term_exact_match(self):
        g = self._make()
        self.assertTrue(g.should_preserve("Plasma Gun"))

    def test_exact_match_is_case_insensitive(self):
        g = self._make()
        self.assertTrue(g.should_preserve("PLASMA GUN"))
        self.assertTrue(g.should_preserve("plasma gun"))

    def test_preserve_category_term_exact_match(self):
        g = self._make()
        # "Power Sword" has preserve=False but category "weapon" is in preserve_cats
        self.assertTrue(g.should_preserve("Power Sword"))

    def test_hyphen_variant_of_spaced_term(self):
        g = self._make()
        # Glossary term is "Med Kit" (space); text uses the hyphenated form
        self.assertTrue(g.should_preserve("Med-Kit"))

    def test_non_listed_text_is_not_preserved(self):
        g = self._make()
        self.assertFalse(g.should_preserve("The rain falls on the battlefield today."))

    def test_non_preserve_category_is_not_preserved(self):
        g = self._make()
        # "Imperial Navy" is category "faction" with preserve=False
        self.assertFalse(g.should_preserve("Imperial Navy"))

    def test_contains_match_finds_embedded_term(self):
        g = self._make()
        found, terms = g.should_preserve_with_terms("Equip the Plasma Gun before the fight.")
        self.assertTrue(found)
        self.assertIn("Plasma Gun", terms)

    def test_should_preserve_with_terms_returns_matched_terms(self):
        g = self._make()
        found, terms = g.should_preserve_with_terms("Power Sword")
        self.assertTrue(found)
        self.assertEqual(terms, ["Power Sword"])

    def test_no_match_returns_empty_terms(self):
        g = self._make()
        found, terms = g.should_preserve_with_terms("Completely unrelated sentence here.")
        self.assertFalse(found)
        self.assertEqual(terms, [])

    def test_complete_mode_preserves_nothing(self):
        g = self._make(mode="complete")
        self.assertFalse(g.should_preserve("Plasma Gun"))
        self.assertFalse(g.should_preserve("Power Sword"))
        found, terms = g.should_preserve_with_terms("Equip the Plasma Gun before the fight.")
        self.assertFalse(found)
        self.assertEqual(terms, [])

    def test_missing_glossary_file_loads_empty(self):
        g = SmartGlossary(os.path.join(self._tmp.name, "nope.json"), preserve_mode="preserve")
        self.assertEqual(g.entries, {})
        self.assertFalse(g.should_preserve("Plasma Gun"))


class TestSplitBatch(unittest.TestCase):
    def _items(self, n, text_len=20):
        # 20 chars -> estimate_tokens = 5
        return [(f"uuid-{i}", {"Offset": i, "Text": "x" * text_len}) for i in range(n)]

    def test_respects_token_cap_and_keeps_order(self):
        items = self._items(5)  # 5 tokens each, cap 10 -> batches of 2,2,1
        batches = split_batch(items, max_tok=10)
        self.assertEqual([len(b) for b in batches], [2, 2, 1])
        flattened = [kv for b in batches for kv in b]
        self.assertEqual(flattened, items)
        for b in batches:
            total = sum(estimate_tokens(v["Text"]) for _, v in b)
            self.assertLessEqual(total, 10)

    def test_oversized_single_item_gets_own_batch(self):
        items = [("big", {"Offset": 0, "Text": "y" * 100})] + self._items(5)
        batches = split_batch(items, max_tok=10)
        self.assertEqual([len(b) for b in batches], [1, 2, 2, 1])
        self.assertEqual(batches[0][0][0], "big")
        flattened = [kv for b in batches for kv in b]
        self.assertEqual(flattened, items)

    def test_empty_input(self):
        self.assertEqual(split_batch([]), [])


class TestLoadBlacklist(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)

    def _write(self, name, data):
        path = os.path.join(self._tmp.name, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        return path

    def test_list_form(self):
        path = self._write("bl.json", ["aaa-111", "bbb-222"])
        self.assertEqual(load_blacklist(path), {"aaa-111", "bbb-222"})

    def test_dict_form(self):
        path = self._write("bl.json", {"ccc-333": {"reason": "EULA"}, "ddd-444": {}})
        self.assertEqual(load_blacklist(path), {"ccc-333", "ddd-444"})

    def test_missing_file_returns_empty(self):
        self.assertEqual(load_blacklist(os.path.join(self._tmp.name, "nope.json")), set())

    def test_none_path_returns_empty(self):
        self.assertEqual(load_blacklist(None), set())


class TestAtomicSave(unittest.TestCase):
    def test_writes_valid_json_without_leftovers(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.json")
            data = {"strings": {"u1": {"Offset": 0, "Text": "Coração do Imperador"}}}
            atomic_save(data, path)
            with open(path, "r", encoding="utf-8") as f:
                self.assertEqual(json.load(f), data)
            # Only the target file may remain — no temp files left behind
            self.assertEqual(os.listdir(tmp), ["out.json"])

    def test_creates_missing_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sub", "dir", "out.json")
            atomic_save({"a": 1}, path)
            with open(path, "r", encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"a": 1})


if __name__ == "__main__":
    unittest.main()
