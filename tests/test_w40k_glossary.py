"""Testes de w40k_glossary — jornada ⑤ Glossário (stdlib only).

LLM e wiki ao vivo são mockados na camada HTTP (opener injetável);
wiki offline usa wiki_sync.get_wiki_data monkeypatchado — nada de rede,
nada de %APPDATA%/keyring reais.
"""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import _isolate  # noqa: F401 — isola W40K_CONFIG_DIR (flat discovery)
except ImportError:
    pass

import w40k_glossary as gl
import w40k_project as wp


def make_glossary(tmp: Path, terms: list) -> Path:
    path = tmp / "glossary.json"
    path.write_text(json.dumps({
        "metadata": {"version": "2.1", "name": "Rogue Trader",
                     "game": "rogue_trader", "total_terms": len(terms)},
        "terms": terms,
    }), encoding="utf-8")
    return path


def entry(en, pt=None, category="talent", preserve=True, inline=False,
          source="wh40k_wiki", usage=1):
    return {
        "term_english": en,
        "term_translated": pt if pt is not None else en,
        "category": category,
        "preserve": preserve,
        "inline": inline,
        "source": source,
        "context": f"WH40K Wiki — {category}",
        "confidence": "medium",
        "usage_count": usage,
        "created_at": "2026-06-17T22:52:09",
    }


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.addCleanup(self._td.cleanup)
        self.tmp = Path(self._td.name)


class TestLoadSave(TempDirCase):
    def test_load_tolerates_missing_and_malformed(self):
        data = gl.load_glossary(self.tmp / "nada.json")
        self.assertEqual(data, {"metadata": {}, "terms": []})
        bad = self.tmp / "bad.json"
        bad.write_text("{lixo", encoding="utf-8")
        data = gl.load_glossary(bad)
        self.assertEqual(data["terms"], [])

    def test_atomic_write_updates_metadata(self):
        path = self.tmp / "g.json"
        data = {"metadata": {"name": "X"}, "terms": [entry("A"), entry("B")]}
        gl.atomic_write_glossary(path, data)
        saved = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(saved["metadata"]["total_terms"], 2)
        self.assertIn("updated_at", saved["metadata"])
        self.assertFalse((self.tmp / "g.json.tmp").exists())

    def test_save_project_glossary_updates_stamp(self):
        project = wp.Project.create(self.tmp / "proj")
        project.import_glossary(make_glossary(
            self.tmp, [entry("Voidship", "Voidship", "weapon")]))
        data = gl.load_glossary(project.glossary_path())
        gl.add_term(data, entry("Plasma Gun", "Arma de Plasma", "weapon"))
        stamp = gl.save_project_glossary(project, data)
        self.assertEqual(stamp["terms"], 2)
        project2 = wp.Project.open(project.root)
        self.assertEqual(project2.state["glossary_stamp"]["terms"], 2)

    def test_backup_glossary_into_backups(self):
        project = wp.Project.create(self.tmp / "proj")
        project.import_glossary(make_glossary(self.tmp, [entry("A")]))
        dest = gl.backup_glossary(project)
        self.assertIsNotNone(dest)
        self.assertTrue(dest.is_file())
        self.assertIn("backups", str(dest))
        self.assertIn("glossary_pre-edit_", dest.name)


class TestCrud(TempDirCase):
    def test_add_validates_and_dedupes_case_insensitive(self):
        data = {"metadata": {}, "terms": [entry("Voidship")]}
        with self.assertRaises(ValueError):
            gl.add_term(data, entry("voidship"))
        with self.assertRaises(ValueError):
            gl.add_term(data, entry(""))
        added = gl.add_term(data, entry("Plasma Gun", "Arma de Plasma"))
        self.assertEqual(added["term_translated"], "Arma de Plasma")

    def test_normalize_defaults(self):
        n = gl.normalize_entry({"term_english": "X"})
        self.assertEqual(n["term_translated"], "X")
        self.assertEqual(n["category"], gl.DEFAULT_CATEGORY)
        self.assertTrue(n["preserve"])
        self.assertFalse(n["inline"])
        self.assertEqual(n["confidence"], "medium")
        self.assertIn("created_at", n)

    def test_update_preserves_created_and_usage(self):
        data = {"metadata": {}, "terms": [
            entry("Voidship", "Voidship", usage=42)]}
        gl.update_term(data, "Voidship",
                       entry("Voidship", "Nave Estelar", usage=1))
        t = data["terms"][gl.find_term(data["terms"], "Voidship")]
        self.assertEqual(t["term_translated"], "Nave Estelar")
        self.assertEqual(t["usage_count"], 42)

    def test_update_rename_dup_rejected(self):
        data = {"metadata": {}, "terms": [entry("A"), entry("B")]}
        with self.assertRaises(ValueError):
            gl.update_term(data, "A", entry("b"))
        gl.update_term(data, "A", entry("C"))
        self.assertEqual(gl.find_term(data["terms"], "A"), -1)
        self.assertGreaterEqual(gl.find_term(data["terms"], "C"), 0)

    def test_remove(self):
        data = {"metadata": {}, "terms": [entry("A"), entry("B")]}
        self.assertTrue(gl.remove_term(data, "a"))
        self.assertFalse(gl.remove_term(data, "A"))
        self.assertEqual(len(data["terms"]), 1)


class TestFilter(unittest.TestCase):
    def setUp(self):
        self.terms = [
            entry("Plasma Gun", "Arma de Plasma", "weapon"),
            entry("Voidship", "Voidship", "weapon", inline=True),
            entry("Medicae", "Médicae", "skill", preserve=False),
            entry("Bolt Pistol", "Pistola Bolter", "weapon"),
        ]

    def test_text_search_en_pt(self):
        self.assertEqual(len(gl.filter_terms(self.terms, "plasma")), 1)
        self.assertEqual(len(gl.filter_terms(self.terms, "bolter")), 1)
        self.assertEqual(len(gl.filter_terms(self.terms)), 4)

    def test_category_and_flags(self):
        self.assertEqual(len(gl.filter_terms(
            self.terms, category="skill")), 1)
        self.assertEqual(len(gl.filter_terms(
            self.terms, category="weapon", inline=True)), 1)
        self.assertEqual(len(gl.filter_terms(
            self.terms, preserve=False)), 1)

    def test_categories_of(self):
        self.assertEqual(gl.categories_of(self.terms), ["skill", "weapon"])


class TestCandidateScan(TempDirCase):
    def test_scan_rows_have_defaults_and_context(self):
        project = wp.Project.create(self.tmp / "proj")
        loc = self.tmp / "enGB.json"
        strings = {
            f"u{i}": {"Offset": i,
                      "Text": f"The Star Port guards Voidship Alpha "
                              f"near Star Port bay {i}."}
            for i in range(5)
        }
        strings["skip"] = {"Offset": 9, "Text": "TBD"}
        loc.write_text(json.dumps({"strings": strings}), encoding="utf-8")
        project.set_input(loc)
        gloss = make_glossary(self.tmp, [entry("Voidship Alpha")])
        rows = gl.scan_project_candidates(project, gloss, min_count=3)
        terms = [r["term"] for r in rows]
        self.assertIn("Star Port", terms)
        self.assertNotIn("Voidship Alpha", terms)  # já no glossário
        row = rows[terms.index("Star Port")]
        self.assertGreaterEqual(row["count"], 3)
        self.assertIn("Star Port", row["context"])
        self.assertTrue(row["preserve"])           # default visível
        self.assertTrue(row["approved"])
        self.assertEqual(row["source"], gl.SOURCE_AUTO_BUILD)

    def test_guess_category_inherits_from_existing(self):
        existing = [entry("Plasma Gun", category="weapon"),
                    entry("Medicae", category="skill")]
        self.assertEqual(gl.guess_category("Plasma Cannon", existing),
                         "weapon")
        self.assertEqual(gl.guess_category("Zygor Prime", existing),
                         gl.DEFAULT_CATEGORY)


class TestMerge(TempDirCase):
    def test_merge_dedupes_and_stamps(self):
        data = {"metadata": {}, "terms": [entry("Voidship")]}
        added, skipped = gl.merge_terms(data, [
            entry("voidship"),          # dup case-insensitive
            entry("Plasma Gun"),
            entry("Medicae"),
        ])
        self.assertEqual((added, skipped), (2, 1))
        self.assertEqual(data["metadata"]["total_terms"], 3)

    def test_entries_from_rows_rules(self):
        rows = [
            {"term": "Star Port", "pt": "Porto Estelar", "approved": True,
             "category": "location", "preserve": True, "inline": False,
             "count": 7, "source": gl.SOURCE_AUTO_BUILD, "context": "…"},
            {"term": "Void Kraken", "pt": "Kraken do Vazio", "approved": True,
             "category": "mod", "preserve": True, "inline": True,
             "count": 4, "source": gl.SOURCE_AUTO_BUILD_LLM, "context": "…"},
            {"term": "Rejected", "pt": "", "approved": False,
             "category": "mod", "preserve": True, "inline": False,
             "count": 3, "source": gl.SOURCE_AUTO_BUILD, "context": ""},
        ]
        entries = gl.entries_from_candidate_rows(rows)
        self.assertEqual(len(entries), 2)  # rejeitado ficou de fora
        manual, llm = entries
        self.assertEqual(manual["confidence"], "medium")
        self.assertEqual(manual["usage_count"], 7)
        self.assertEqual(llm["confidence"], "low")   # revisão pendente
        self.assertEqual(llm["source"], "auto_build_llm")
        self.assertTrue(llm["inline"])


class TestLlmSuggestion(unittest.TestCase):
    TERMS = ["Star Port", "Void Kraken", "Medicae Veil"]

    def test_prompt_is_numbered_single_batch(self):
        system, user = gl.build_llm_prompt(self.TERMS)
        self.assertIn("PT-BR", user)
        for i, t in enumerate(self.TERMS):
            self.assertIn(f"{i + 1}. {t}", user)

    def test_parse_json_list(self):
        content = json.dumps([{"en": t, "pt": f"PT::{t}"}
                              for t in self.TERMS])
        out = gl.parse_llm_suggestions(content, self.TERMS)
        self.assertEqual(out["Star Port"], "PT::Star Port")
        self.assertEqual(len(out), 3)

    def test_parse_tolerates_fences_dict_and_numbering(self):
        content = "```json\n{\"1. Star Port\": \"Porto Estelar\", " \
                  "\"void kraken\": \"Kraken do Vazio\", " \
                  "\"Unknown Term\": \"ignorar\"}\n```"
        out = gl.parse_llm_suggestions(content, self.TERMS)
        self.assertEqual(out["Star Port"], "Porto Estelar")
        self.assertEqual(out["Void Kraken"], "Kraken do Vazio")
        self.assertNotIn("Unknown Term", out)
        self.assertNotIn("Medicae Veil", out)  # sem sugestão, sem crash

    def test_parse_line_fallback(self):
        content = "Star Port = Porto Estelar\nVoid Kraken — Kraken do Vazio"
        out = gl.parse_llm_suggestions(content, self.TERMS)
        self.assertEqual(out["Star Port"], "Porto Estelar")
        self.assertEqual(out["Void Kraken"], "Kraken do Vazio")

    def test_suggest_uses_one_batched_call(self):
        calls = []
        content = json.dumps([{"en": t, "pt": f"PT::{t}"}
                              for t in self.TERMS])
        body = json.dumps({"choices": [{"message": {"content": content}}]})

        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return body.encode()

        def fake_opener(req, timeout=0):
            calls.append(req)
            return _Resp()

        out = gl.suggest_translations_llm(
            self.TERMS, "glm-4.7-flash", "sk-x",
            "https://glm.example/v1", opener=fake_opener)
        self.assertEqual(len(calls), 1)  # UMA chamada
        self.assertEqual(out["Medicae Veil"], "PT::Medicae Veil")
        payload = json.loads(calls[0].data.decode())
        self.assertEqual(payload["model"], "glm-4.7-flash")
        for t in self.TERMS:
            self.assertIn(t, payload["messages"][1]["content"])

    def test_suggest_requires_key(self):
        with self.assertRaises(ValueError):
            gl.suggest_translations_llm(self.TERMS, "m", "", "https://x")


class TestWikiSeed(unittest.TestCase):
    def test_offline_seed_entries(self):
        import wiki_sync
        original = wiki_sync.get_wiki_data
        wiki_sync.get_wiki_data = lambda path=None: {
            "weapon": ["Plasma Gun", "Bolt Pistol"],
            "skill": ["Medicae"],
        }
        try:
            entries = gl.wiki_seed_entries()
            filtered = gl.wiki_seed_entries(only_cats=["skill"])
        finally:
            wiki_sync.get_wiki_data = original
        self.assertEqual(len(entries), 3)
        self.assertEqual(entries[0]["category"], "weapon")
        self.assertTrue(all(e["preserve"] for e in entries))
        self.assertTrue(all(e["source"] == "wh40k_wiki" for e in entries))
        self.assertEqual(len(filtered), 1)

    def test_live_fetch_parses_mediawiki(self):
        calls = []

        class _Resp:
            def __init__(self, obj):
                self.obj = obj

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps(self.obj).encode()

        wikitext = "{{Weapon\n|type=Plasma\n|rarity=Rare\n"
        page_obj = {"query": {"pages": {"1": {
            "title": "Plasma Gun",
            "revisions": [{"slots": {"main": {"*": wikitext}}}]}}}}

        def fake_opener(req, timeout=0):
            url = req.full_url if hasattr(req, "full_url") else str(req)
            calls.append(url)
            if "list=search" in url:
                return _Resp({"query": {"search": [
                    {"title": "Plasma Gun"}]}})
            return _Resp(page_obj)

        entry_out = gl.wiki_fetch_live("plasma gun", opener=fake_opener)
        self.assertEqual(len(calls), 2)  # search → wikitext
        self.assertEqual(entry_out["term_english"], "Plasma Gun")
        self.assertEqual(entry_out["category"], "weapon")
        self.assertEqual(entry_out["source"], "live_wiki")
        self.assertTrue(entry_out["preserve"])
        self.assertIn("type=Plasma", entry_out["context"])

    def test_live_fetch_not_found(self):
        class _Resp:
            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

            def read(self):
                return json.dumps({"query": {"search": []}}).encode()

        with self.assertRaises(ValueError):
            gl.wiki_fetch_live("xyz-nada", opener=lambda r, timeout=0: _Resp())


if __name__ == "__main__":
    unittest.main()
