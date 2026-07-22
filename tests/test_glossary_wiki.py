# -*- coding: utf-8 -*-
"""Tests for glossary_manager.py (entry model + load/save) and
wiki_sync.get_wiki_data() (offline wiki term dataset from JSON).

No network: get_wiki_data() loads data/glossaries/wiki_terms.json only.
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from glossary_manager import GlossaryEntry, load_glossary, save_glossary
from wiki_sync import get_wiki_data


class TestGlossaryEntry(unittest.TestCase):
    def test_to_dict_from_dict_round_trip(self):
        entry = GlossaryEntry(
            term_english="Plasma Gun",
            term_translated="Arma de Plasma",
            category="weapon",
            context="Ranged weapon",
            confidence="high",
            first_seen_batch=3,
            usage_count=7,
            created_at="2026-01-01T12:00:00",
        )
        clone = GlossaryEntry.from_dict(entry.to_dict())
        self.assertEqual(clone, entry)
        self.assertEqual(clone.to_dict(), entry.to_dict())

    def test_created_at_auto_filled(self):
        entry = GlossaryEntry(term_english="X", term_translated="Y", category="outro")
        self.assertTrue(entry.created_at)

    def test_defaults(self):
        entry = GlossaryEntry(term_english="X", term_translated="Y", category="outro")
        self.assertEqual(entry.context, "")
        self.assertEqual(entry.confidence, "high")
        self.assertEqual(entry.usage_count, 1)
        self.assertEqual(entry.first_seen_batch, 0)


class TestLoadSaveGlossary(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "glossary.json")

    def test_missing_file_returns_initialized_structure(self):
        data = load_glossary(self.path)
        self.assertEqual(data["terms"], [])
        self.assertEqual(data["metadata"]["total_terms"], 0)
        self.assertIn("version", data["metadata"])
        self.assertIn("updated_at", data["metadata"])

    def test_save_updates_metadata_counts(self):
        data = load_glossary(self.path)
        data["terms"].append({"term_english": "A", "term_translated": "B", "category": "outro"})
        data["terms"].append({"term_english": "C", "term_translated": "D", "category": "outro"})
        save_glossary(self.path, data)

        with open(self.path, "r", encoding="utf-8") as f:
            saved = json.load(f)
        self.assertEqual(saved["metadata"]["total_terms"], 2)
        self.assertTrue(saved["metadata"]["updated_at"])
        self.assertEqual(len(saved["terms"]), 2)

    def test_save_then_load_round_trip(self):
        data = load_glossary(self.path)
        data["terms"].append({"term_english": "Plasma Gun", "term_translated": "Arma de Plasma",
                              "category": "weapon", "preserve": True})
        save_glossary(self.path, data)
        reloaded = load_glossary(self.path)
        self.assertEqual(reloaded["terms"], data["terms"])
        self.assertEqual(reloaded["metadata"]["total_terms"], 1)


class TestWikiData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.wiki = get_wiki_data()

    def test_sixteen_categories(self):
        self.assertEqual(len(self.wiki), 16)

    def test_total_term_count(self):
        total = sum(len(terms) for terms in self.wiki.values())
        self.assertGreater(total, 2500)

    def test_no_category_is_empty(self):
        for category, terms in self.wiki.items():
            self.assertGreater(len(terms), 0, f"category {category!r} is empty")

    def test_every_term_is_a_non_empty_string(self):
        for category, terms in self.wiki.items():
            for term in terms:
                self.assertIsInstance(term, str, f"{category}: {term!r}")
                self.assertTrue(term.strip(), f"{category}: blank term {term!r}")


if __name__ == "__main__":
    unittest.main()
