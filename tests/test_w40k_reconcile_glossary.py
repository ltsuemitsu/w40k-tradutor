"""Testes de reconciliação de estado (§9.6) e glossário por projeto (§9.7).

Stdlib-only: roda sem PySide6 com `python -m unittest discover -s tests`.
O teste do engine (SmartGlossary) é pulado se tradutor.py não importar.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import w40k_project as wp

REPO_ROOT = Path(__file__).resolve().parent.parent

try:
    import tradutor as engine
    _HAVE_ENGINE = True
except Exception:  # pragma: no cover - ambiente sem tqdm
    engine = None
    _HAVE_ENGINE = False


def make_loc(path: Path, entries: dict) -> Path:
    strings = {}
    for i, (uid, val) in enumerate(entries.items()):
        if isinstance(val, dict):
            strings[uid] = {"Offset": i * 16, **val}
        else:
            strings[uid] = {"Offset": i * 16, "Text": val}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"strings": strings}, ensure_ascii=False),
                    encoding="utf-8")
    return path


EN_TEXTS = {
    "u-1": "The voidship drifts through the darkness.",
    "u-2": "This weapon deals massive damage to enemies.",
    "u-3": "You have acquired a new talent for your hero.",
}
PT_TEXTS = {
    "u-1": "A nave à deriva atravessa a escuridão.",
    "u-2": "Esta arma causa dano massivo aos inimigos.",
    "u-3": "Você adquiriu um novo talento para o herói.",
}


class TempProjectCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="w40k_rec_test_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.project = wp.Project.create(self.tmp / "proj")


class TestReconcile(TempProjectCase):
    def test_detects_untracked_canonical_and_versioned(self):
        make_loc(self.project.root / "input" / "enGB_1.6.1.514.json",
                 EN_TEXTS)
        make_loc(self.project.root / "output" / "ptBR_full_1.6.1.514.json",
                 PT_TEXTS)
        untracked = self.project.reconcile()["untracked"]
        by_name = {i["name"]: i for i in untracked}
        self.assertEqual(set(by_name), {"enGB_1.6.1.514.json",
                                        "ptBR_full_1.6.1.514.json"})
        self.assertEqual(by_name["enGB_1.6.1.514.json"]["role"],
                         wp.ROLE_EN_INPUT)
        self.assertEqual(by_name["ptBR_full_1.6.1.514.json"]["role"],
                         wp.ROLE_FULL)
        self.assertTrue(all(i["sha256"] for i in untracked))

    def test_ignores_already_tracked_by_sha(self):
        # Registra input + output canônicos via adoção.
        src_en = make_loc(self.tmp / "enGB.json", EN_TEXTS)
        src_pt = make_loc(self.tmp / "ptBR_full.json", PT_TEXTS)
        self.project.adopt_files({wp.ROLE_EN_INPUT: src_en,
                                  wp.ROLE_FULL: src_pt})
        # Mesma CONTEÚDO versionado ao lado (duplicata de arquivo) →
        # não é novidade (sha bate com o registrado).
        make_loc(self.project.root / "input" / "enGB_1.6.1.514.json",
                 EN_TEXTS)
        self.assertEqual(self.project.reconcile()["untracked"], [])

    def test_detects_sha_mismatch_on_canonical(self):
        src_en = make_loc(self.tmp / "enGB.json", EN_TEXTS)
        self.project.adopt_files({wp.ROLE_EN_INPUT: src_en})
        # Usuário sobrescreveu o canonical à mão com conteúdo NOVO.
        make_loc(self.project.input_path(),
                 {**EN_TEXTS, "u-4": "A brand new string."})
        untracked = self.project.reconcile()["untracked"]
        self.assertEqual([i["name"] for i in untracked], ["enGB.json"])

    def test_register_in_place_never_copies(self):
        """§2 revisado: o arquivo é registrado ONDE ESTÁ, com o nome que
        tem — nenhuma cópia canônica é criada."""
        versioned = make_loc(
            self.project.root / "output" / "ptBR_full_1.6.1.514.json",
            PT_TEXTS)
        before = sorted(p.name for p in
                        (self.project.root / "output").iterdir())
        result = self.project.adopt_files({wp.ROLE_FULL: versioned})
        self.assertEqual(len(result["imported"]), 1)
        after = sorted(p.name for p in
                       (self.project.root / "output").iterdir())
        self.assertEqual(before, after)  # dir listing idêntico: zero cópias
        entry = self.project.track_status(wp.TRACK_FULL)
        self.assertEqual(entry["status"], wp.TRACK_STATUS_DONE)
        self.assertEqual(entry["file"], "output/ptBR_full_1.6.1.514.json")
        self.assertEqual(entry["translated"], len(PT_TEXTS))
        self.assertEqual(self.project.state["game_version"], "1.6.1.514")
        self.assertEqual(self.project.track_path(wp.TRACK_FULL), versioned)
        # Depois do registro, nada mais aparece como novo (re-prompt fix).
        self.assertEqual(self.project.reconcile()["untracked"], [])

    def test_preserve_map_is_not_a_candidate(self):
        (self.project.root / "output" / "preserve_map.json").write_text(
            "{}", encoding="utf-8")
        self.assertEqual(self.project.reconcile()["untracked"], [])

    def test_stale_track_marks_pending(self):
        src = make_loc(self.tmp / "ptBR_full.json", PT_TEXTS)
        self.project.adopt_files({wp.ROLE_FULL: src})
        self.project.output_path(wp.TRACK_FULL).unlink()  # usuário deletou
        cleaned = self.project.cleanup_stale()
        self.assertEqual(len(cleaned), 1)
        self.assertIn("full", cleaned[0])
        entry = self.project.track_status(wp.TRACK_FULL)
        self.assertEqual(entry["status"], wp.TRACK_STATUS_PENDING)
        self.assertEqual(entry["translated"], 0)

    def test_stale_input_marks_pending(self):
        src = make_loc(self.tmp / "enGB.json", EN_TEXTS)
        self.project.set_input(src)
        self.project.input_path().unlink()
        cleaned = self.project.cleanup_stale()
        self.assertEqual(len(cleaned), 1)
        self.assertIn("input", cleaned[0])
        self.assertIsNone(self.project.state["input"]["file"])

    def test_cleanup_stale_noop_when_files_exist(self):
        src = make_loc(self.tmp / "ptBR_full.json", PT_TEXTS)
        self.project.adopt_files({wp.ROLE_FULL: src})
        self.assertEqual(self.project.cleanup_stale(), [])
        entry = self.project.track_status(wp.TRACK_FULL)
        self.assertEqual(entry["status"], wp.TRACK_STATUS_DONE)


class TestProjectGlossary(TempProjectCase):
    def test_import_rt_metadata_additive(self):
        stamp = self.project.import_glossary(REPO_ROOT / "glossary.json")
        self.assertEqual(stamp["kind"], wp.GLOSSARY_KIND_BASE)
        self.assertEqual(stamp["name"], "Rogue Trader")
        self.assertIsNone(stamp["parent"])
        self.assertIsNone(stamp["mod_name"])
        self.assertEqual(stamp["terms"], 2694)
        dest = self.project.glossary_path()
        self.assertTrue(dest.is_file())
        data = json.loads(dest.read_text(encoding="utf-8"))
        meta = data["metadata"]
        # Campos legados preservados (aditivo) + novos carimbados.
        self.assertEqual(meta["version"], "2.1")
        self.assertEqual(meta["kind"], "base_game")
        self.assertEqual(meta["game"], "rogue_trader")
        self.assertEqual(meta["total_terms"], len(data["terms"]))
        self.assertEqual(len(data["terms"]), 2694)
        # project.json aponta para o glossário do projeto.
        self.assertEqual(self.project.state["glossary"], "glossary.json")
        self.assertEqual(self.project.state["glossary_stamp"]["kind"],
                         "base_game")

    def test_import_mod_kind_with_parent(self):
        stamp = self.project.import_glossary(
            REPO_ROOT / "glossary.json", kind=wp.GLOSSARY_KIND_MOD,
            mod_name="Meu Mod")
        self.assertEqual(stamp["kind"], "mod")
        self.assertEqual(stamp["mod_name"], "Meu Mod")
        self.assertEqual(stamp["name"], "Meu Mod")
        self.assertEqual(stamp["parent"], "Rogue Trader")
        data = json.loads(
            self.project.glossary_path().read_text(encoding="utf-8"))
        self.assertEqual(data["metadata"]["parent"], "Rogue Trader")
        self.assertEqual(data["metadata"]["mod_name"], "Meu Mod")

    def test_create_empty_glossary(self):
        stamp = self.project.create_empty_glossary()
        self.assertEqual(stamp["terms"], 0)
        data = json.loads(
            self.project.glossary_path().read_text(encoding="utf-8"))
        self.assertEqual(data["terms"], [])
        meta = data["metadata"]
        self.assertEqual(meta["kind"], "base_game")
        self.assertEqual(meta["total_terms"], 0)
        self.assertIn("name", meta)

    def test_import_invalid_glossary_raises(self):
        bad = self.tmp / "bad.json"
        bad.write_text('{"nada": true}', encoding="utf-8")
        with self.assertRaises(wp.ProjectError):
            self.project.import_glossary(bad)

    @unittest.skipUnless(_HAVE_ENGINE, "engine (tradutor.py) indisponível")
    def test_extended_metadata_keeps_engine_loadable(self):
        """SmartGlossary lê só 'terms' → metadata extra é inócua."""
        glossary = engine.SmartGlossary(str(REPO_ROOT / "glossary.json"),
                                        "preserve")
        self.assertEqual(len(glossary.entries), 2694)
        # E o glossário importado (metadata carimbada) também carrega.
        self.project.import_glossary(REPO_ROOT / "glossary.json")
        local = engine.SmartGlossary(str(self.project.glossary_path()),
                                     "preserve")
        self.assertEqual(len(local.entries), 2694)


if __name__ == "__main__":
    unittest.main()
