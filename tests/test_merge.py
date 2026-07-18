# -*- coding: utf-8 -*-
"""Tests for merge.py — merging corrections into the main translation file.

merge.py is CLI-shaped, so tests drive main() with a patched sys.argv and
synthetic JSON fixtures in a temp dir. No network, no API keys.
"""
import contextlib
import glob
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import merge


BASE_DATA = {"strings": {
    "uuid-1": {"Offset": 1, "Text": "Texto antigo"},
    "uuid-2": {"Offset": 2, "Text": "Texto intacto"},
}}


def _run_merge(argv):
    """Run merge.main() with patched argv and swallowed stdout."""
    with mock.patch.object(sys, "argv", ["merge.py"] + argv):
        with contextlib.redirect_stdout(io.StringIO()):
            return merge.main()


class TestMerge(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.base = os.path.join(self._tmp.name, "ptBR.json")
        self.corr = os.path.join(self._tmp.name, "fix.json")
        self.out = os.path.join(self._tmp.name, "out.json")
        self._write(self.base, BASE_DATA)

    def _write(self, path, data):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)

    def _read(self, path):
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)

    def test_merge_applies_changes_and_creates_backup(self):
        corrections = {"strings": {
            # Re-translated validator item (Text differs from _current_translation)
            "uuid-1": {"Offset": 1, "Text": "Texto corrigido",
                       "_current_translation": "Old English text", "_issue": "nao traduzido"},
            # Brand-new key not present in the base
            "uuid-3": {"Offset": 3, "Text": "Texto adicionado"},
        }}
        self._write(self.corr, corrections)

        rc = _run_merge(["-b", self.base, "-c", self.corr, "-o", self.out, "--backup"])

        self.assertEqual(rc, 0)
        merged = self._read(self.out)
        self.assertEqual(merged["strings"]["uuid-1"]["Text"], "Texto corrigido")
        self.assertEqual(merged["strings"]["uuid-2"]["Text"], "Texto intacto")
        self.assertEqual(merged["strings"]["uuid-3"]["Text"], "Texto adicionado")
        # Debug metadata from the validator must not leak into the merged entry
        self.assertNotIn("_current_translation", merged["strings"]["uuid-1"])
        self.assertNotIn("_issue", merged["strings"]["uuid-1"])

        backups = glob.glob(f"{self.base}.*.backup")
        self.assertEqual(len(backups), 1)
        self.assertEqual(self._read(backups[0]), BASE_DATA)

    def test_refuses_untranslated_validator_output(self):
        # Every item still has Text == _current_translation (never re-translated)
        corrections = {"strings": {
            "uuid-1": {"Offset": 1, "Text": "Still English",
                       "_current_translation": "Still English", "_issue": "nao traduzido"},
        }}
        self._write(self.corr, corrections)

        rc = _run_merge(["-b", self.base, "-c", self.corr, "-o", self.out, "--backup"])

        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(self.out))
        # Base untouched, no backup created
        self.assertEqual(self._read(self.base), BASE_DATA)
        self.assertEqual(glob.glob(f"{self.base}.*.backup"), [])

    def test_dry_run_changes_nothing(self):
        corrections = {"strings": {
            "uuid-1": {"Offset": 1, "Text": "Texto corrigido"},
        }}
        self._write(self.corr, corrections)

        rc = _run_merge(["-b", self.base, "-c", self.corr, "-o", self.out, "--dry-run"])

        self.assertEqual(rc, 0)
        self.assertFalse(os.path.exists(self.out))
        self.assertEqual(self._read(self.base), BASE_DATA)

    def test_empty_corrections_file_fails(self):
        self._write(self.corr, {"strings": {}})
        rc = _run_merge(["-b", self.base, "-c", self.corr, "-o", self.out])
        self.assertEqual(rc, 1)
        self.assertFalse(os.path.exists(self.out))


if __name__ == "__main__":
    unittest.main()
