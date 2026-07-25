# -*- coding: utf-8 -*-
"""Tests for tradutor.py — core engine pieces that never touch the LLM.

Covered: TagProtector, TermProtector, SmartGlossary classify, fullize_text,
split_batch, load_blacklist, atomic_save.
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
    TermProtector,
    atomic_save,
    estimate_tokens,
    fullize_text,
    is_eula,
    load_blacklist,
    should_skip,
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
        _term("Plasma Gun", "Arma de Plasma", "item", True),        # preserve flag
        _term("Power Sword", "Espada de Energia", "weapon", False),  # preserve category
        _term("Med Kit", "Kit Médico", "item", True),              # space in term
        _term("Imperial Navy", "Marinha Imperial", "faction", False),  # not preserved
    ],
}


class TestTagProtector(unittest.TestCase):
    TAGGED = (
        'You gain {g|talent}Barrage{/g} and {n}move{/n} faster. '
        '<color=#ff0000>Red warning</color> with <sprite=icon_skull> icon '
        'and <link=talent_01>link text</link>.'
    )

    HARD = (
        'Speak to {name}, {mf|his|her} {mf|Lordship|Ladyship}. '
        'Gain {g|Encyclopedia:DamageGlossary}damage{/g}. '
        '{d|Encyclopedia:CharGen_Psyker}lore{/d}. '
        'Hold [{bind|HighlightObjects}] or {mouse_icon|LeftMouse}. '
        'Stat {unit_stat|WarhammerToughness|bonus}. Hint: {0}%. '
        '<indent=5%>line</indent>{br}<sprite name="UI_LeftMouseBTN">'
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
        self.assertTrue(re.findall(r"§TAG\d+§", protected))
        for inner in ("Barrage", "move", "Red warning", "link text"):
            self.assertIn(inner, protected)

    def test_hard_markup_round_trip(self):
        protected, ph = TagProtector.protect(self.HARD)
        restored = TagProtector.restore(protected, ph)
        self.assertEqual(restored, self.HARD)

    def test_hard_markup_no_leaks(self):
        self.assertEqual(TagProtector.leak_scan(self.HARD), [])
        protected, _ = TagProtector.protect(self.HARD)
        for frag in ("{name}", "{mf|", "{bind|", "{mouse_icon|", "{unit_stat|",
                     "{0}", "{br}", "{d|", "{/d}", "<indent", "<sprite"):
            self.assertNotIn(frag, protected)
        # human bits still visible
        self.assertIn("Speak to", protected)
        self.assertIn("damage", protected)
        self.assertIn("lore", protected)
        self.assertIn("Hold", protected)
        self.assertIn("Stat", protected)
        self.assertIn("Hint:", protected)
        self.assertIn("line", protected)

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


class TestTermProtector(unittest.TestCase):
    def test_round_trip_keeps_english_term(self):
        text = "Equip the Plasma Gun before the fight."
        protected, ph = TermProtector.protect(text, ["Plasma Gun"])
        self.assertNotIn("Plasma Gun", protected)
        self.assertTrue(re.search(r"\[\[W40KT\d+\]\]", protected))
        self.assertIn("Equip the", protected)
        restored = TermProtector.restore(protected, ph)
        self.assertEqual(restored, text)

    def test_longest_term_wins(self):
        text = "Use a Plasma Gun now."
        protected, ph = TermProtector.protect(text, ["Plasma Gun", "Gun"])
        # Only one placeholder if Plasma Gun consumed the span
        restored = TermProtector.restore(protected, ph)
        self.assertEqual(restored, text)
        self.assertTrue(any(v == "Plasma Gun" for v in ph.values()))

    def test_no_terms_no_change(self):
        text = "Hello world"
        protected, ph = TermProtector.protect(text, [])
        self.assertEqual(protected, text)
        self.assertEqual(ph, {})

    def test_after_tag_protect_still_works(self):
        text = "Gain {g|item}Plasma Gun{/g} now."
        t, tph = TagProtector.protect(text)
        t2, term_ph = TermProtector.protect(t, ["Plasma Gun"])
        tph.update(term_ph)
        # LLM would translate outer words; we only check restore
        restored = TermProtector.restore(TagProtector.restore(t2, tph), tph)
        # at least term comes back
        self.assertIn("Plasma Gun", restored)

    def test_mangled_legacy_term_placeholder_restores(self):
        text = "Hello Rogue Trader."
        prot, ph = TermProtector.protect(text, ["Rogue Trader"])
        # LLM renumbers / uses old § form
        fake = "Hello §TERM0§."
        self.assertEqual(TermProtector.restore(fake, ph), "Hello Rogue Trader.")


class TestGenderTags(unittest.TestCase):
    def test_mf_him_her(self):
        from tradutor import localize_gender_tags
        s = '"Trono... É? É {mf|him|her}!"'
        self.assertEqual(localize_gender_tags(s), '"Trono... É? É {mf|ele|ela}!"')

    def test_mf_his_her_case(self):
        from tradutor import localize_gender_tags
        self.assertIn("{mf|Seu|Sua}", localize_gender_tags("{mf|His|Her}"))
        self.assertIn("{mf|seu|sua}", localize_gender_tags("{mf|his|her}"))

    def test_rt_mf(self):
        from tradutor import localize_gender_tags
        self.assertEqual(
            localize_gender_tags("{rt_mf|he|she}"),
            "{rt_mf|ele|ela}",
        )


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
        kind, terms = g.classify_preserve("Plasma Gun")
        self.assertEqual(kind, "exact")
        self.assertEqual(terms, ["Plasma Gun"])

    def test_exact_match_is_case_insensitive(self):
        g = self._make()
        self.assertTrue(g.should_preserve("PLASMA GUN"))
        self.assertTrue(g.should_preserve("plasma gun"))

    def test_preserve_category_term_exact_match(self):
        g = self._make()
        self.assertTrue(g.should_preserve("Power Sword"))

    def test_hyphen_variant_of_spaced_term(self):
        g = self._make()
        self.assertTrue(g.should_preserve("Med-Kit"))

    def test_non_listed_text_is_clean(self):
        g = self._make()
        self.assertFalse(g.should_preserve("The rain falls on the battlefield today."))
        kind, terms = g.classify_preserve("The rain falls on the battlefield today.")
        self.assertEqual(kind, "clean")
        self.assertEqual(terms, [])

    def test_non_preserve_category_is_not_preserved(self):
        g = self._make()
        self.assertFalse(g.should_preserve("Imperial Navy"))
        kind, _ = g.classify_preserve("Imperial Navy")
        self.assertEqual(kind, "clean")

    def test_inline_does_not_skip_whole_string(self):
        """BUG FIX: contains match must be inline, NOT whole-string preserve."""
        g = self._make()
        phrase = "Equip the Plasma Gun before the fight."
        self.assertFalse(g.should_preserve(phrase))  # exact-only
        kind, terms = g.classify_preserve(phrase)
        self.assertEqual(kind, "inline")
        self.assertIn("Plasma Gun", terms)

    def test_should_preserve_with_terms_still_flags_inline(self):
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
        kind, terms = g.classify_preserve("Equip the Plasma Gun before the fight.")
        self.assertEqual(kind, "clean")
        self.assertEqual(terms, [])

    def test_inline_false_skips_phrase_but_keeps_exact(self):
        """Polysemes: exact EN skip stays; no lock inside longer phrases."""
        data = {
            "metadata": {},
            "terms": [
                _term("Command", "Comando", "ability", True),
                _term("Plasma Gun", "Arma de Plasma", "weapon", True),
            ],
        }
        data["terms"][0]["inline"] = False
        path = os.path.join(self._tmp.name, "soft.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        g = SmartGlossary(path, preserve_mode="preserve")
        self.assertEqual(g.classify_preserve("Command")[0], "exact")
        self.assertEqual(g.classify_preserve("You issue a Command now.")[0], "clean")
        self.assertEqual(g.classify_preserve("Equip a Plasma Gun.")[0], "inline")

    def test_missing_glossary_file_loads_empty(self):
        g = SmartGlossary(os.path.join(self._tmp.name, "nope.json"), preserve_mode="preserve")
        self.assertEqual(g.entries, {})
        self.assertFalse(g.should_preserve("Plasma Gun"))


class TestFullize(unittest.TestCase):
    def test_replaces_en_with_pt(self):
        en_to_pt = {"Plasma Gun": "Arma de Plasma", "Power Sword": "Espada de Energia"}
        out = fullize_text("Equip the Plasma Gun and a Power Sword.", en_to_pt)
        self.assertEqual(out, "Equip the Arma de Plasma and a Espada de Energia.")

    def test_skips_when_en_equals_pt(self):
        out = fullize_text("Plasma Gun ready.", {"Plasma Gun": "Plasma Gun"})
        self.assertEqual(out, "Plasma Gun ready.")

    def test_longest_first(self):
        en_to_pt = {"Gun": "Arma", "Plasma Gun": "Arma de Plasma"}
        out = fullize_text("Plasma Gun", en_to_pt)
        self.assertEqual(out, "Arma de Plasma")


class TestSkipAndEula(unittest.TestCase):
    def test_empty_and_placeholder_skipped(self):
        self.assertTrue(should_skip(""))
        self.assertTrue(should_skip("   "))
        self.assertTrue(should_skip("placeholder"))
        self.assertTrue(should_skip("[placeholder]"))
        self.assertTrue(should_skip("TODO"))
        self.assertFalse(should_skip("A real sentence for the player."))

    def test_eula_by_length(self):
        self.assertFalse(is_eula("Short legal note."))
        self.assertTrue(is_eula("x" * 15001))
        # 3001 chars of words, >2000 words
        blob = ("word " * 2100).strip()
        self.assertGreater(len(blob), 3000)
        self.assertTrue(is_eula(blob))

    def test_eula_keyword_needs_volume(self):
        self.assertFalse(is_eula("This EULA is short."))
        # 4 words * 200 = 800 words, length well over 3000
        mid = ("end user license agreement. " * 200)
        self.assertGreater(len(mid), 3000)
        self.assertGreater(len(mid.split()), 500)
        self.assertTrue(is_eula(mid))
        # narrative-sized text is not EULA even if long-ish
        narrative = ("The void ship groaned as the warp storm rose. " * 40)
        self.assertGreater(len(narrative), 1000)
        self.assertLess(len(narrative), 3000)
        self.assertFalse(is_eula(narrative))


class TestSplitBatch(unittest.TestCase):
    def _items(self, n, text_len=20):
        return [(f"uuid-{i}", {"Offset": i, "Text": "x" * text_len}) for i in range(n)]

    def test_respects_token_cap_and_keeps_order(self):
        items = self._items(5)
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
            self.assertEqual(os.listdir(tmp), ["out.json"])

    def test_creates_missing_parent_dirs(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "sub", "dir", "out.json")
            atomic_save({"a": 1}, path)
            with open(path, "r", encoding="utf-8") as f:
                self.assertEqual(json.load(f), {"a": 1})


# ─────────────────────────────────────────────────────────────────────────────
# Execução paralela (Issue 1) — cliente OpenAI FAKE contando concorrência
# ─────────────────────────────────────────────────────────────────────────────

import threading
import time
import types

import tradutor as _trad_module
import w40k_preflight as _pf


class _ConcurrencyHarness:
    """Instala um módulo `openai` fake em sys.modules e roda tradutor.main()
    contando o máximo de chamadas simultâneas em voo."""

    def __init__(self):
        self.in_flight = 0
        self.max_in_flight = 0
        self.calls = 0
        self.client_kwargs = []
        self._lock = threading.Lock()

    def install(self):
        harness = self

        class _Completions:
            def create(self, model, messages, temperature,
                       response_format=None):
                with harness._lock:
                    harness.in_flight += 1
                    harness.calls += 1
                    harness.max_in_flight = max(harness.max_in_flight,
                                                harness.in_flight)
                try:
                    time.sleep(0.05)  # latência simulada da API
                    user = messages[-1]["content"]
                    payload = user[user.index("```json\n") + 8:
                                   user.rindex("\n```")]
                    texts = json.loads(payload)
                    msg = types.SimpleNamespace(
                        message=types.SimpleNamespace(
                            content=json.dumps([f"PT::{t}" for t in texts],
                                               ensure_ascii=False)))
                    return types.SimpleNamespace(choices=[msg])
                finally:
                    with harness._lock:
                        harness.in_flight -= 1

        class _FakeOpenAI:
            def __init__(self, api_key=None, base_url=None, **kwargs):
                harness.client_kwargs.append(dict(kwargs))
                self.chat = types.SimpleNamespace(completions=_Completions())

        fake = types.ModuleType("openai")
        fake.OpenAI = _FakeOpenAI
        sys.modules["openai"] = fake

    def run_engine(self, strings: dict, extra_args: list,
                   tmp: Path) -> int:
        inp = tmp / "in.json"
        out = tmp / "out.json"
        inp.write_text(json.dumps({"strings": strings}), encoding="utf-8")
        argv = ["tradutor.py", "-i", str(inp), "-o", str(out),
                "--mode", "complete",
                "--prescan-cache", str(tmp / "nada.json")] + extra_args
        old_argv = sys.argv
        sys.argv = argv
        try:
            return _trad_module.main()
        finally:
            sys.argv = old_argv


def _mixed_strings(n_short, n_medium, n_long, n_xlong):
    strings = {}
    for i in range(n_short):
        strings[f"s{i}"] = {"Offset": i, "Text": f"Hi {i}"}
    for i in range(n_medium):
        strings[f"m{i}"] = {"Offset": i, "Text": "M" * 100 + str(i)}
    for i in range(n_long):
        strings[f"l{i}"] = {"Offset": i, "Text": "L" * 500 + str(i)}
    for i in range(n_xlong):
        strings[f"x{i}"] = {"Offset": i, "Text": "X" * 1500 + str(i)}
    return strings


class TestParallelExecution(unittest.TestCase):
    def setUp(self):
        self._old_key = os.environ.get("DEEPSEEK_API_KEY")
        os.environ["DEEPSEEK_API_KEY"] = "fake-key"
        self.harness = _ConcurrencyHarness()
        self.harness.install()

    def tearDown(self):
        if self._old_key is None:
            os.environ.pop("DEEPSEEK_API_KEY", None)
        else:
            os.environ["DEEPSEEK_API_KEY"] = self._old_key

    def test_batches_run_in_parallel_with_profile_autobump(self):
        """Sem -w (caminho do wizard): perfil flash → 8 workers, e batches
        independentes realmente voam juntos (max concorrência == workers)."""
        strings = _mixed_strings(200, 100, 30, 10)  # 8 batches no perfil
        with tempfile.TemporaryDirectory() as tmp:
            rc = self.harness.run_engine(
                strings, ["--model", "deepseek-v4-flash"], Path(tmp))
        self.assertEqual(rc, 0)
        self.assertEqual(self.harness.calls, 8)   # 8 batches
        self.assertEqual(self.harness.max_in_flight, 8)  # 8 workers

    def test_explicit_workers_are_respected_literally(self):
        """-w explícito NÃO sofre auto-bump — é assim que os overrides de
        workers das Configurações chegam ao engine."""
        strings = _mixed_strings(200, 100, 30, 10)
        with tempfile.TemporaryDirectory() as tmp:
            rc = self.harness.run_engine(
                strings, ["--model", "deepseek-v4-flash", "-w", "3"],
                Path(tmp))
        self.assertEqual(rc, 0)
        # Antes do fix, -w 3 == DEFAULT_MAX_WORKERS → auto-bump para 8.
        self.assertEqual(self.harness.max_in_flight, 3)

    def test_client_created_with_max_retries_1(self):
        """Sem retry duplo: o backoff vive no nível do batch; o SDK não pode
        re-tentar por dentro (workers paralelos viravam fila de sleeps)."""
        strings = _mixed_strings(0, 60, 0, 0)  # 2 batches médios
        with tempfile.TemporaryDirectory() as tmp:
            rc = self.harness.run_engine(
                strings, ["--model", "deepseek-v4-flash", "-w", "2"],
                Path(tmp))
        self.assertEqual(rc, 0)
        self.assertTrue(self.harness.client_kwargs)
        for kwargs in self.harness.client_kwargs:
            self.assertEqual(kwargs.get("max_retries"), 1)


class TestPrescanCacheConsumption(unittest.TestCase):
    """Engine consome o cache do Pre-Scan (w40k_preflight.write_prescan_cache)
    e pula a re-classificação: skip/eula/preserved marcados em O(1)."""

    def test_engine_uses_prescan_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            gloss = tmp / "glossary.json"
            gloss.write_text(json.dumps({"terms": [
                _term("Voidship", "Voidship", "weapon", True),
            ]}), encoding="utf-8")
            inp = tmp / "in.json"
            inp.write_text(json.dumps({"strings": {
                "k-skip": {"Offset": 0, "Text": "TBD"},
                "k-eula": {"Offset": 1, "Text": (
                    "End User License Agreement. " + "legal terms " * 600)},
                "k-pres": {"Offset": 2, "Text": "Voidship"},
                "k-api": {"Offset": 3, "Text": "A narrative line."},
            }}), encoding="utf-8")
            cache = tmp / "prescan_cache.json"
            counts = _pf.write_prescan_cache(inp, gloss, cache,
                                             mode="preserve")
            self.assertEqual(counts, {"PRESERVED": 1, "SKIP": 1, "EULA": 1})
            shape = json.loads(cache.read_text(encoding="utf-8"))
            self.assertIn("source_hash", shape)
            self.assertEqual(shape["preserve_mode"], "preserve")
            self.assertEqual(shape["buckets"]["PRESERVED"], ["k-pres"])

            harness = _ConcurrencyHarness()
            harness.install()
            out = tmp / "out.json"
            argv = ["tradutor.py", "-i", str(inp), "-o", str(out),
                    "--mode", "preserve", "--dry-run",
                    "--prescan-cache", str(cache),
                    "--preserve-map", str(tmp / "pm.json"),
                    "-g", str(gloss)]
            old_argv = sys.argv
            sys.argv = argv
            try:
                rc = _trad_module.main()
            finally:
                sys.argv = old_argv
            self.assertEqual(rc, 0)
            data = json.loads(out.read_text(encoding="utf-8"))["strings"]
            self.assertEqual(data["k-skip"]["_skipped"], "prescan_skip")
            self.assertEqual(data["k-eula"]["_skipped"], "eula")
            self.assertTrue(data["k-pres"]["_preserved"])
            self.assertNotIn("_failed", data["k-api"])

    def test_stale_cache_is_ignored(self):
        """source_hash divergente → engine ignora o cache (re-classifica)."""
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            inp = tmp / "in.json"
            inp.write_text(json.dumps({"strings": {
                "k-skip": {"Offset": 0, "Text": "TBD"},
            }}), encoding="utf-8")
            cache = tmp / "prescan_cache.json"
            cache.write_text(json.dumps({
                "source_hash": "hash-de-outro-arquivo",
                "preserve_mode": "preserve",
                "buckets": {"PRESERVED": [], "SKIP": ["k-skip"], "EULA": []},
            }), encoding="utf-8")
            out = tmp / "out.json"
            argv = ["tradutor.py", "-i", str(inp), "-o", str(out),
                    "--mode", "preserve", "--dry-run",
                    "--prescan-cache", str(cache),
                    "--preserve-map", str(tmp / "pm.json")]
            old_argv = sys.argv
            sys.argv = argv
            try:
                rc = _trad_module.main()
            finally:
                sys.argv = old_argv
            self.assertEqual(rc, 0)
            data = json.loads(out.read_text(encoding="utf-8"))["strings"]
            # Cache ignorado → classificação normal do engine ("placeholder").
            self.assertEqual(data["k-skip"]["_skipped"], "placeholder")


if __name__ == "__main__":
    unittest.main()
