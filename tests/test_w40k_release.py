"""Testes do módulo de release (w40k_release.py) — Fase 3.

Stdlib-only: roda sem PySide6 com `python -m unittest discover -s tests`.
"""

import json
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import w40k_project as wp
import w40k_release as rl


def make_loc(path: Path, texts: dict) -> Path:
    data = {
        "strings": {
            uid: {"Offset": i * 16, "Text": text}
            for i, (uid, text) in enumerate(texts.items())
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


PRES_TEXTS = {"u1": "A nave à deriva no vazio.", "u2": "Plasma Gun",
              "u3": "Você venceu."}
FULL_TEXTS = {"u1": "A nave à deriva no vazio.", "u2": "Arma de Plasma",
              "u3": "Você venceu."}


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="w40k_rl_test_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.project = wp.Project.create(self.tmp / "proj")
        self.pres = make_loc(
            self.project.output_path(wp.TRACK_PRESERVED), PRES_TEXTS)
        self.full = make_loc(
            self.project.output_path(wp.TRACK_FULL), FULL_TEXTS)


class TestNamesAndValidation(TempDirCase):
    def test_zip_name_convention(self):
        self.assertEqual(rl.release_zip_name(wp.TRACK_FULL, "1.6.1.514"),
                         "traducao_FULL_1.6.1.514.zip")
        self.assertEqual(rl.release_zip_name(wp.TRACK_PRESERVED, "2.0.1"),
                         "traducao_PRESERVED_2.0.1.zip")

    def test_snapshot_name(self):
        self.assertEqual(rl.src_snapshot_name(wp.TRACK_FULL, "1.6.1.514"),
                         "traducao_FULL_1.6.1.514_src.json")

    def test_zip_name_unknown_track(self):
        with self.assertRaises(wp.ProjectError):
            rl.release_zip_name("outra", "1.0.0")

    def test_version_validation(self):
        self.assertEqual(rl.validate_release_version(" 1.6.1.514 "),
                         "1.6.1.514")
        with self.assertRaises(wp.ProjectError):
            rl.validate_release_version("")
        with self.assertRaises(wp.ProjectError):
            rl.validate_release_version("1.6-beta")


class TestFullizeHelpers(TempDirCase):
    def test_build_fullize_args(self):
        args = rl.build_fullize_args(Path("tradutor.py"), self.project,
                                     Path("glossary.json"))
        self.assertIn("--fullize", args)
        self.assertEqual(args[args.index("-i") + 1], str(self.pres))
        self.assertEqual(args[args.index("-o") + 1], str(self.full))
        self.assertEqual(args[args.index("-g") + 1], "glossary.json")

    def test_parse_fullize_line(self):
        parsed = rl.parse_fullize_line(
            "12:00 [INFO] Fullize: 18312 strings altered | "
            "out=output/ptBR_full.json | glossary pairs=2694")
        self.assertEqual(parsed, {"changed": 18312, "pairs": 2694})
        self.assertIsNone(rl.parse_fullize_line("outra linha"))

    def test_needs_refullize(self):
        # full mais novo que preserved → False
        self.assertFalse(rl.needs_refullize(self.project))
        # mexer na preserved → mais nova → True
        import os, time
        time.sleep(0.02)
        os.utime(self.pres, None)
        self.assertTrue(rl.needs_refullize(self.project))
        # sem full → True; sem preserved → False
        self.full.unlink()
        self.assertTrue(rl.needs_refullize(self.project))
        self.pres.unlink()
        self.assertFalse(rl.needs_refullize(self.project))


class TestDiff(TempDirCase):
    def test_count_changed_strings(self):
        # FULL difere da PRESERVED em u2 ("Plasma Gun" → "Arma de Plasma")
        self.assertEqual(rl.count_changed_strings(self.pres, self.full), 1)

    def test_count_changed_new_strings(self):
        newer = make_loc(self.tmp / "novo.json",
                         {**PRES_TEXTS, "u4": "String nova."})
        self.assertEqual(rl.count_changed_strings(self.pres, newer), 1)


class TestExport(TempDirCase):
    def test_export_full_zip_contents(self):
        result = rl.export_release(self.project, wp.TRACK_FULL, "1.6.1.514")
        self.assertEqual(result["zip_name"], "traducao_FULL_1.6.1.514.zip")
        self.assertTrue(result["zip"].is_file())

        with zipfile.ZipFile(result["zip"]) as zf:
            names = zf.namelist()
            self.assertIn("enGB.json", names)       # nome exigido pelo jogo
            self.assertIn("LEIA-ME_INSTALACAO.txt", names)
            self.assertIn("CHANGELOG.txt", names)

            engb = json.loads(zf.read("enGB.json").decode("utf-8"))
            self.assertEqual(len(engb["strings"]), len(FULL_TEXTS))
            self.assertEqual(
                engb["strings"]["u2"]["Text"], "Arma de Plasma")

            readme = zf.read("LEIA-ME_INSTALACAO.txt").decode("utf-8")
            self.assertIn(r"WH40KRT_Data\StreamingAssets\Localization",
                          readme)
            self.assertIn("1.6.1.514", readme)
            self.assertIn("COMPLETA", readme)
            self.assertIn("TRADUÇÃO DE FÃ", readme)

            changelog = zf.read("CHANGELOG.txt").decode("utf-8")
            self.assertIn("v1.6.1.514", changelog)
            self.assertIn("Primeira release", changelog)

        # Snapshot para o próximo diff.
        snap = self.project.root / "release" / \
            "traducao_FULL_1.6.1.514_src.json"
        self.assertTrue(snap.is_file())

        # Registro no project.json.
        state = json.loads(
            (self.project.root / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(len(state["releases"]), 1)
        rel = state["releases"][0]
        self.assertEqual(rel["version"], "1.6.1.514")
        self.assertEqual(rel["track"], "full")
        self.assertEqual(rel["file"],
                         "release/traducao_FULL_1.6.1.514.zip")
        self.assertTrue(rel["date"])

    def test_export_preserved_naming(self):
        result = rl.export_release(self.project, wp.TRACK_PRESERVED, "1.0.0")
        self.assertEqual(result["zip_name"],
                         "traducao_PRESERVED_1.0.0.zip")
        with zipfile.ZipFile(result["zip"]) as zf:
            readme = zf.read("LEIA-ME_INSTALACAO.txt").decode("utf-8")
            self.assertIn("PRESERVADA", readme)

    def test_changelog_with_diff_since_previous(self):
        rl.export_release(self.project, wp.TRACK_FULL, "1.0.0")
        # Altera o output e exporta de novo → changelog cita o diff.
        make_loc(self.full, {**FULL_TEXTS, "u2": "Arma de Plasma Mk II",
                             "u4": "Nova string."})
        result = rl.export_release(self.project, wp.TRACK_FULL, "1.1.0")
        self.assertEqual(result["prev_version"], "1.0.0")
        self.assertEqual(result["diff_count"], 2)  # u2 mudou + u4 nova
        with zipfile.ZipFile(result["zip"]) as zf:
            changelog = zf.read("CHANGELOG.txt").decode("utf-8")
            self.assertIn("2 strings alteradas desde v1.0.0", changelog)

    def test_diff_since_last_release(self):
        self.assertIsNone(rl.diff_since_last_release(self.project,
                                                     wp.TRACK_FULL))
        rl.export_release(self.project, wp.TRACK_FULL, "1.0.0")
        diff = rl.diff_since_last_release(self.project, wp.TRACK_FULL)
        self.assertEqual(diff, (0, "1.0.0"))

    def test_export_gates(self):
        # Sem output da trilha → erro PT-BR.
        projeto_vazio = wp.Project.create(self.tmp / "vazio")
        with self.assertRaises(wp.ProjectError) as ctx:
            rl.export_release(projeto_vazio, wp.TRACK_FULL, "1.0.0")
        self.assertIn("Não existe tradução", str(ctx.exception))

        # Versão inválida.
        with self.assertRaises(wp.ProjectError):
            rl.export_release(self.project, wp.TRACK_FULL, "abc")

    def test_full_requires_preserved(self):
        projeto = wp.Project.create(self.tmp / "so_full")
        make_loc(projeto.output_path(wp.TRACK_FULL), FULL_TEXTS)
        with self.assertRaises(wp.ProjectError) as ctx:
            rl.export_release(projeto, wp.TRACK_FULL, "1.0.0")
        self.assertIn("fullize", str(ctx.exception))


class TestRecordRelease(TempDirCase):
    def test_record_release_persists(self):
        self.project.record_release("1.0.0", wp.TRACK_FULL,
                                    "release/x.zip")
        reopened = wp.Project.open(self.project.root)
        rel = reopened.state["releases"][0]
        self.assertEqual(rel["version"], "1.0.0")
        self.assertEqual(rel["track"], "full")
        self.assertTrue(rel["date"])


if __name__ == "__main__":
    unittest.main()
