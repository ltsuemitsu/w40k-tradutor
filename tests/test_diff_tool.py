# -*- coding: utf-8 -*-
"""Tests for diff_tool.py — audit, update detection, smart diff.

Pure functions over synthetic Owlcat localization dicts:
{"strings": {"<uuid>": {"Offset": int, "Text": str}}}. No network, no files needed.
"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from diff_tool import audit_translation, detect_update, smart_diff


def _loc(entries):
    """entries: dict uuid -> text. Builds a localization dict."""
    return {"strings": {k: {"Offset": i, "Text": t} for i, (k, t) in enumerate(entries.items())}}


EMPTY_GLOSSARY = {"metadata": {}, "terms": []}


class TestDetectUpdate(unittest.TestCase):
    def test_only_added_and_changed_in_delta(self):
        en_old = _loc({
            "uuid-1": "Hello world.",
            "uuid-2": "The Emperor protects.",
            "uuid-3": "This string was removed.",
        })
        en_new = _loc({
            "uuid-1": "Hello world.",                  # unchanged
            "uuid-2": "The Emperor protects us all.",  # modified
            "uuid-4": "Brand new string.",             # added
        })
        pt_current = _loc({"uuid-1": "Olá mundo.", "uuid-2": "O Imperador protege."})

        result = detect_update(en_new, en_old, pt_current)

        self.assertEqual({k for k, _ in result["new_keys"]}, {"uuid-4"})
        self.assertEqual({k for k, _, _ in result["modified_keys"]}, {"uuid-2"})
        self.assertEqual(set(result["removed_keys"]), {"uuid-3"})
        self.assertEqual(set(result["unchanged_keys"]), {"uuid-1"})

    def test_modified_entry_carries_old_text(self):
        en_old = _loc({"uuid-2": "Old wording."})
        en_new = _loc({"uuid-2": "New wording."})
        result = detect_update(en_new, en_old, _loc({}))
        _, item, old_text = result["modified_keys"][0]
        self.assertEqual(item["Text"], "New wording.")
        self.assertEqual(old_text, "Old wording.")


class TestAuditTranslation(unittest.TestCase):
    def test_flags_untranslated_and_accepts_translated(self):
        orig = _loc({
            "uuid-1": "The sword causes damage to the enemy.",
            "uuid-2": "The door is locked tight.",
        })
        trans = _loc({
            "uuid-1": "A espada causa dano ao inimigo.",   # properly translated
            "uuid-2": "The door is locked tight.",         # EN == PT: untranslated
        })
        cats = audit_translation(orig, trans, EMPTY_GLOSSARY)

        identical_keys = {k for k, _, _ in cats["identical"]}
        ok_keys = {k for k, _, _ in cats["ok"]}
        self.assertIn("uuid-2", identical_keys)
        self.assertIn("uuid-1", ok_keys)
        self.assertNotIn("uuid-1", identical_keys)
        self.assertNotIn("uuid-2", ok_keys)

    def test_glossary_term_is_not_flagged_as_untranslated(self):
        glossary = {"metadata": {}, "terms": [{
            "term_english": "Plasma Gun", "term_translated": "Plasma Gun",
            "category": "weapon", "preserve": True,
        }]}
        orig = _loc({"uuid-1": "Plasma Gun"})
        trans = _loc({"uuid-1": "Plasma Gun"})  # same text, but it is a glossary term
        cats = audit_translation(orig, trans, glossary)
        preserved_keys = {k for k, _, _ in cats["glossary_preserved"]}
        identical_keys = {k for k, _, _ in cats["identical"]}
        self.assertIn("uuid-1", preserved_keys)
        self.assertNotIn("uuid-1", identical_keys)


class TestSmartDiff(unittest.TestCase):
    GLOSSARY = {"metadata": {}, "terms": [{
        "term_english": "Plasma Gun", "term_translated": "Plasma Gun",
        "category": "weapon", "preserve": True, "source": "test",
        "context": "", "confidence": "high", "usage_count": 1,
        "created_at": "2026-01-01T00:00:00",
    }]}

    def test_flags_needs_work_and_detects_preserved_in_context(self):
        orig = _loc({
            "uuid-1": "Equip the Plasma Gun before the fight.",
            "uuid-2": "The door is locked tight.",
            "uuid-3": "The window hangs open today.",
        })
        trans = _loc({
            # Translated, keeps the glossary term in EN (correct behavior)
            "uuid-1": "Equipe a Plasma Gun antes da luta.",
            # Fully translated, no glossary term involved
            "uuid-2": "A porta está bem trancada.",
            # Untranslated -> needs work
            "uuid-3": "The window hangs open today.",
        })
        result, needs_work = smart_diff(orig, trans, self.GLOSSARY)

        preserved_keys = {k for k, _, _, _ in result["preserved"]}
        ok_keys = {k for k, _, _ in result["ok"]}
        needs_keys = {k for k, _, _, _ in needs_work}

        self.assertIn("uuid-1", preserved_keys)
        # The glossary term found in context is reported
        for k, _, _, found_terms in result["preserved"]:
            if k == "uuid-1":
                self.assertIn("Plasma Gun", found_terms)
        self.assertIn("uuid-2", ok_keys)
        self.assertIn("uuid-3", needs_keys)
        self.assertEqual(result["needs_work"], needs_work)

    def test_pure_mechanic_name_is_ok_even_untranslated(self):
        orig = _loc({"uuid-1": "Plasma Gun"})
        trans = _loc({"uuid-1": "Plasma Gun"})
        result, needs_work = smart_diff(orig, trans, self.GLOSSARY)
        ok_keys = {k for k, _, _ in result["ok"]}
        self.assertIn("uuid-1", ok_keys)
        self.assertEqual(needs_work, [])


if __name__ == "__main__":
    unittest.main()
