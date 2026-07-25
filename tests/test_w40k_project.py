"""Testes da camada de projeto da nova GUI (w40k_project.py) — Fase 1.

Roda sem PySide6: `python -m unittest discover -s tests`.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import w40k_project as wp


def make_loc(path: Path, texts: dict) -> Path:
    """Escreve um JSON de localização sintético {strings: {id: {Offset, Text}}}."""
    data = {
        "strings": {
            uid: {"Offset": i * 16, "Text": text}
            for i, (uid, text) in enumerate(texts.items())
        }
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


EN_TEXTS = {
    "uuid-en-1": "The voidship drifts through the darkness of the void.",
    "uuid-en-2": "You have acquired a new talent for your character.",
    "uuid-en-3": "This weapon deals massive damage to the target and all "
                 "enemies in the area of effect.",
    "uuid-en-4": "The Rogue Trader is the master of this vessel and you "
                 "are bound to serve the dynasty.",
    "uuid-en-5": "Press the button to continue your journey into the Koronus "
                 "Expanse with your retinue.",
}

PT_FULL_TEXTS = {
    "uuid-pt-1": "A nave à deriva atravessa a escuridão do vazio.",
    "uuid-pt-2": "Você adquiriu um novo talento para o seu personagem.",
    "uuid-pt-3": "Esta arma causa dano massivo ao alvo e a todos os "
                 "inimigos na área de efeito.",
    "uuid-pt-4": "O Comerciante Independente é o senhor desta embarcação e "
                 "você está ligado à dinastia.",
    "uuid-pt-5": "Pressione o botão para continuar sua jornada pela "
                 "Extensão Koronus com seu séquito.",
}

# Trilha Preservada: narrativa traduzida + vários termos de mecânica em EN.
PT_PRESERVED_TEXTS = {
    "uuid-pr-1": "A nave à deriva atravessa a escuridão do vazio.",
    "uuid-pr-2": "Você adquiriu um novo talento para o seu personagem.",
    "uuid-pr-3": "Esta arma causa dano massivo ao alvo.",
    "uuid-pr-4": "Plasma Gun",
    "uuid-pr-5": "Weapon Skill",
    "uuid-pr-6": "Ballistic Skill",
    "uuid-pr-7": "Medicae",
    "uuid-pr-8": "Power Armour",
    "uuid-pr-9": "Bolter",
    "uuid-pr-10": "O Comerciante é o senhor desta embarcação e você está "
                  "ligado à dinastia.",
}


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="w40k_test_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))


class TestScaffold(TempDirCase):
    def test_create_makes_subdirs_and_project_json(self):
        folder = self.tmp / "MeuProjeto"
        project = wp.Project.create(folder)

        for sub in wp.SUBDIRS:
            self.assertTrue((folder / sub).is_dir(), f"faltou pasta {sub}")
        self.assertTrue((folder / "project.json").is_file())

        state = json.loads((folder / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(state["app_version"], wp.APP_VERSION)
        self.assertEqual(state["game_profile"], "rogue_trader")
        self.assertIn("preserved", state["tracks"])
        self.assertIn("full", state["tracks"])
        self.assertEqual(state["tracks"]["preserved"]["status"], "pending")
        self.assertEqual(state["input"]["strings"], 0)
        self.assertEqual(state["releases"], [])
        self.assertIsNone(state["last_audit"])
        self.assertEqual(project.root, folder)

    def test_create_refuses_existing_project(self):
        folder = self.tmp / "p"
        wp.Project.create(folder)
        with self.assertRaises(wp.ProjectError):
            wp.Project.create(folder)

    def test_create_with_glossary_stamp(self):
        gloss = self.tmp / "glossary.json"
        gloss.write_text(json.dumps(
            {"metadata": {"version": "2.1"}, "terms": [{"a": 1}] * 42}),
            encoding="utf-8")
        project = wp.Project.create(self.tmp / "p", glossary_path=gloss)
        self.assertEqual(project.state["glossary_stamp"]["terms"], 42)
        self.assertEqual(project.state["glossary_stamp"]["built_for"],
                         "rogue_trader")

    def test_create_with_unreadable_glossary_still_works(self):
        bad = self.tmp / "bad.json"
        bad.write_text("não é json", encoding="utf-8")
        project = wp.Project.create(self.tmp / "p", glossary_path=bad)
        self.assertEqual(project.state["glossary_stamp"]["terms"], 0)


class TestOpenProject(TempDirCase):
    def test_round_trip(self):
        folder = self.tmp / "p"
        project = wp.Project.create(folder)
        project.state["game_version"] = "1.3.2"
        project.update_track("preserved", "done", translated=100,
                             skipped_free=20)
        project.save()

        reopened = wp.Project.open(folder)
        self.assertEqual(reopened.state["game_version"], "1.3.2")
        track = reopened.state["tracks"]["preserved"]
        self.assertEqual(track["status"], "done")
        self.assertEqual(track["translated"], 100)
        self.assertEqual(track["skipped_free"], 20)
        self.assertIsNotNone(track["updated"])

    def test_open_repairs_missing_subfolders(self):
        folder = self.tmp / "p"
        wp.Project.create(folder)
        shutil.rmtree(folder / "audit")
        shutil.rmtree(folder / "backups")
        wp.Project.open(folder)
        self.assertTrue((folder / "audit").is_dir())
        self.assertTrue((folder / "backups").is_dir())

    def test_open_missing_project_json(self):
        with self.assertRaises(wp.ProjectValidationError):
            wp.Project.open(self.tmp / "vazio")

    def test_open_invalid_json(self):
        folder = self.tmp / "p"
        folder.mkdir()
        (folder / "project.json").write_text("{ quebrado", encoding="utf-8")
        with self.assertRaises(wp.ProjectValidationError):
            wp.Project.open(folder)

    def test_open_migrates_missing_fields(self):
        folder = self.tmp / "p"
        folder.mkdir()
        old = {"app_version": "1.0", "input": {"file": None},
               "tracks": {"preserved": {"status": "done"}}}
        (folder / "project.json").write_text(json.dumps(old), encoding="utf-8")
        project = wp.Project.open(folder)
        # Campos novos preenchidos, dados antigos preservados.
        self.assertIn("releases", project.state)
        self.assertEqual(project.state["tracks"]["preserved"]["status"], "done")
        self.assertIn("full", project.state["tracks"])


class TestLocalizationHelpers(TempDirCase):
    def test_sha256_stable(self):
        f = make_loc(self.tmp / "a.json", {"u1": "hello"})
        d1 = wp.sha256_of_file(f)
        d2 = wp.sha256_of_file(f)
        self.assertEqual(d1, d2)
        self.assertEqual(len(d1), 64)

    def test_count_strings(self):
        f = make_loc(self.tmp / "a.json", EN_TEXTS)
        self.assertEqual(wp.count_strings(f), len(EN_TEXTS))

    def test_count_strings_invalid_json(self):
        f = self.tmp / "bad.json"
        f.write_text("não é json", encoding="utf-8")
        with self.assertRaises(wp.LocalizationFormatError):
            wp.count_strings(f)

    def test_count_strings_wrong_schema(self):
        f = self.tmp / "schema.json"
        f.write_text(json.dumps({"data": [1, 2, 3]}), encoding="utf-8")
        with self.assertRaises(wp.LocalizationFormatError):
            wp.count_strings(f)
        self.assertFalse(wp.is_localization_json(f))

    def test_schema_missing_text_field(self):
        f = self.tmp / "notext.json"
        f.write_text(json.dumps({"strings": {
            f"u{i}": {"Offset": i, "Label": f"x{i}"} for i in range(10)}}),
            encoding="utf-8")
        self.assertFalse(wp.is_localization_json(f))


class TestClassification(TempDirCase):
    def setUp(self):
        super().setUp()
        self.en = make_loc(self.tmp / "enGB.json", EN_TEXTS)
        self.full = make_loc(self.tmp / "ptBR_full.json", PT_FULL_TEXTS)
        self.pres = make_loc(self.tmp / "ptBR_preserved.json",
                             PT_PRESERVED_TEXTS)

    def test_en_dump_detected_as_input(self):
        info = wp.classify_file(self.en)
        self.assertTrue(info["valid"])
        self.assertEqual(info["language"], "en")
        self.assertEqual(info["role"], wp.ROLE_EN_INPUT)
        self.assertEqual(info["strings"], len(EN_TEXTS))

    def test_full_pt_detected_as_full_track(self):
        info = wp.classify_file(self.full)
        self.assertTrue(info["valid"])
        self.assertEqual(info["language"], "pt")
        self.assertEqual(info["role"], wp.ROLE_FULL)

    def test_preserved_pt_detected_by_mechanic_terms(self):
        info = wp.classify_file(self.pres)
        self.assertTrue(info["valid"])
        self.assertEqual(info["language"], "pt")
        self.assertEqual(info["role"], wp.ROLE_PRESERVED)

    def test_preserved_hint_from_preserve_map(self):
        # Arquivo full, mas com preserve_map.json vizinho → preservada.
        folder = self.tmp / "out"
        f = make_loc(folder / "ptBR.json", PT_FULL_TEXTS)
        (folder / "preserve_map.json").write_text("{}", encoding="utf-8")
        info = wp.classify_file(f)
        self.assertEqual(info["role"], wp.ROLE_PRESERVED)

    def test_preserved_hint_from_markers(self):
        data = {"strings": {
            f"u{i}": {"Offset": i, "Text": t, "_preserved": i == 0}
            for i, t in enumerate(PT_FULL_TEXTS.values())}}
        f = self.tmp / "marked.json"
        f.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        info = wp.classify_file(f)
        self.assertEqual(info["role"], wp.ROLE_PRESERVED)

    def test_invalid_file_gets_error_not_exception(self):
        f = self.tmp / "lixo.json"
        f.write_text("definitivamente não é json", encoding="utf-8")
        info = wp.classify_file(f)
        self.assertFalse(info["valid"])
        self.assertIsNotNone(info["error"])
        self.assertEqual(info["role"], wp.ROLE_IGNORE)

    def test_non_localization_json_ignored(self):
        f = self.tmp / "config.json"
        f.write_text(json.dumps({"theme": "dark"}), encoding="utf-8")
        info = wp.classify_file(f)
        self.assertFalse(info["valid"])
        self.assertEqual(info["role"], wp.ROLE_IGNORE)

    def test_scan_candidates_folder(self):
        extras = self.tmp / "not_json.txt"
        extras.write_text("texto", encoding="utf-8")
        results = wp.scan_candidates([self.tmp])
        names = sorted(r["name"] for r in results)
        self.assertIn("enGB.json", names)
        self.assertIn("ptBR_full.json", names)
        self.assertNotIn("not_json.txt", names)

    def test_scan_candidates_dedupes(self):
        results = wp.scan_candidates([self.en, self.en, self.tmp / "enGB.json"])
        self.assertEqual(len(results), 1)


class TestAdoption(TempDirCase):
    def setUp(self):
        super().setUp()
        self.src = self.tmp / "originais"
        self.en = make_loc(self.src / "enGB.json", EN_TEXTS)
        self.full = make_loc(self.src / "saida_full.json", PT_FULL_TEXTS)
        self.pres = make_loc(self.src / "saida_preserved.json",
                             PT_PRESERVED_TEXTS)
        self.project = wp.Project.create(self.tmp / "projeto")

    def test_adopt_copies_never_moves(self):
        result = self.project.adopt_files({
            wp.ROLE_EN_INPUT: self.en,
            wp.ROLE_PRESERVED: self.pres,
            wp.ROLE_FULL: self.full,
        })
        self.assertEqual(result["errors"], [])
        self.assertEqual(len(result["imported"]), 3)

        # Originais intactos; cópias dentro do projeto COM O MESMO NOME
        # (convenção §2: nunca renomeia para nomes canônicos).
        for src in (self.en, self.full, self.pres):
            self.assertTrue(src.is_file())
        self.assertTrue((self.project.root / "input" / "enGB.json").is_file())
        self.assertTrue(
            (self.project.root / "output" / "saida_preserved.json").is_file())
        self.assertTrue(
            (self.project.root / "output" / "saida_full.json").is_file())

        # Backfill do project.json.
        state = json.loads(
            (self.project.root / "project.json").read_text(encoding="utf-8"))
        self.assertEqual(state["input"]["file"], "input/enGB.json")
        self.assertEqual(state["input"]["strings"], len(EN_TEXTS))
        self.assertEqual(len(state["input"]["sha256"]), 64)

        for track, texts in (("preserved", PT_PRESERVED_TEXTS),
                             ("full", PT_FULL_TEXTS)):
            entry = state["tracks"][track]
            self.assertEqual(entry["status"], "done")
            self.assertEqual(entry["translated"], len(texts))
            self.assertIsNotNone(entry["updated"])

    def test_adopt_partial_and_error_resilience(self):
        bad = self.src / "quebrado.json"
        bad.write_text("inválido", encoding="utf-8")
        result = self.project.adopt_files({
            wp.ROLE_EN_INPUT: self.en,
            wp.ROLE_PRESERVED: bad,
        })
        self.assertEqual(len(result["imported"]), 1)
        self.assertEqual(len(result["errors"]), 1)
        # O que deu certo foi persistido mesmo com erro no outro arquivo.
        self.assertEqual(self.project.state["input"]["strings"],
                         len(EN_TEXTS))
        self.assertEqual(self.project.state["tracks"]["preserved"]["status"],
                         "pending")

    def test_adopt_persists_across_reopen(self):
        self.project.adopt_files({wp.ROLE_FULL: self.full})
        reopened = wp.Project.open(self.project.root)
        self.assertEqual(reopened.state["tracks"]["full"]["status"], "done")
        self.assertTrue(reopened.has_any_output())
        self.assertFalse(reopened.has_input())

    def test_set_input_registers_sha_and_count(self):
        dest = self.project.set_input(self.en)
        self.assertTrue(dest.is_file())
        self.assertEqual(self.project.state["input"]["strings"],
                         len(EN_TEXTS))
        self.assertEqual(self.project.state["input"]["sha256"],
                         wp.sha256_of_file(dest))
        self.assertTrue(self.project.has_input())

    def test_track_progress(self):
        self.assertIsNone(self.project.track_progress("preserved"))
        self.project.set_input(self.en)
        self.assertEqual(self.project.track_progress("preserved"), 0.0)
        self.project.update_track("preserved", "done", translated=4,
                                  skipped_free=1)
        self.assertAlmostEqual(
            self.project.track_progress("preserved"), 5 / len(EN_TEXTS))

    def test_adopt_backfills_original_name_and_game_version(self):
        versioned_en = make_loc(self.src / "enGB_1.6.1.514.json", EN_TEXTS)
        result = self.project.adopt_files({wp.ROLE_EN_INPUT: versioned_en})
        self.assertEqual(result["errors"], [])

        state = json.loads(
            (self.project.root / "project.json").read_text(encoding="utf-8"))
        # Nome versionado PRESERVADO (§2) — origem e versão registradas.
        self.assertEqual(state["input"]["file"], "input/enGB_1.6.1.514.json")
        self.assertEqual(state["input"]["original_name"],
                         "enGB_1.6.1.514.json")
        self.assertEqual(state["game_version"], "1.6.1.514")

    def test_adopt_detects_version_from_output_name(self):
        # Sem EN na adoção: versão vem do nome do output.
        versioned_full = make_loc(self.src / "ptBR_full_1.6.1.514.json",
                                  PT_FULL_TEXTS)
        result = self.project.adopt_files({wp.ROLE_FULL: versioned_full})
        self.assertEqual(result["errors"], [])
        self.assertEqual(self.project.state["game_version"], "1.6.1.514")

    def test_adopt_keeps_existing_version_when_detection_empty(self):
        self.project.state["game_version"] = "9.9.9"
        self.project.save()
        self.project.adopt_files({wp.ROLE_EN_INPUT: self.en})  # sem versão
        self.assertEqual(self.project.state["game_version"], "9.9.9")

    def test_set_input_backfills_original_name_and_version(self):
        versioned = make_loc(self.src / "enGB_1.3.2.json", EN_TEXTS)
        self.project.set_input(versioned)
        info = self.project.state["input"]
        # §2: registra com o nome versionado, sem renomear.
        self.assertEqual(info["file"], "input/enGB_1.3.2.json")
        self.assertEqual(info["original_name"], "enGB_1.3.2.json")
        self.assertEqual(self.project.state["game_version"], "1.3.2")

    def test_set_input_without_version_keeps_existing(self):
        self.project.set_game_version("1.6.1.514")
        self.project.set_input(self.en)  # enGB.json: sem versão no nome
        self.assertEqual(self.project.state["game_version"], "1.6.1.514")
        self.assertEqual(self.project.state["input"]["original_name"],
                         "enGB.json")


class TestGameVersion(TempDirCase):
    def test_extract_four_groups(self):
        self.assertEqual(
            wp.extract_game_version("enGB_1.6.1.514.json"), "1.6.1.514")

    def test_extract_three_groups(self):
        self.assertEqual(wp.extract_game_version("enGB_1.3.2.json"), "1.3.2")

    def test_extract_from_output_and_zip_names(self):
        self.assertEqual(
            wp.extract_game_version("ptBR_full_1.6.1.514.json"), "1.6.1.514")
        self.assertEqual(
            wp.extract_game_version("ptBR_preserved_2.0.1.json"), "2.0.1")
        self.assertEqual(
            wp.extract_game_version("traducao_FULL_1.6.1.514.zip"),
            "1.6.1.514")

    def test_extract_unversioned_returns_empty(self):
        self.assertEqual(wp.extract_game_version("enGB.json"), "")
        self.assertEqual(wp.extract_game_version("ptBR_full.json"), "")
        self.assertEqual(wp.extract_game_version("backup_final2.json"), "")

    def test_extract_two_groups_not_enough(self):
        self.assertEqual(wp.extract_game_version("enGB_1.6.json"), "")

    def test_extract_ignores_dates_and_paths(self):
        self.assertEqual(wp.extract_game_version("2025-09-10_delta.json"), "")
        self.assertEqual(
            wp.extract_game_version(r"C:\dumps\v2\enGB_1.6.1.514.json"),
            "1.6.1.514")

    def test_set_game_version_valid(self):
        project = wp.Project.create(self.tmp / "p")
        project.set_game_version("1.6.1.514")
        self.assertEqual(project.state["game_version"], "1.6.1.514")
        reopened = wp.Project.open(self.tmp / "p")
        self.assertEqual(reopened.state["game_version"], "1.6.1.514")

    def test_set_game_version_clear_and_invalid(self):
        project = wp.Project.create(self.tmp / "p")
        project.set_game_version("1.6.1")
        project.set_game_version("")  # limpa → desconhecida
        self.assertIsNone(project.state["game_version"])
        with self.assertRaises(wp.ProjectError):
            project.set_game_version("1.6.1-beta")
        with self.assertRaises(wp.ProjectError):
            project.set_game_version("abc")


    def test_replaced_input_never_reoffered(self):
        """Patch Day: o dump ANTIGO fica arquivado em input/ — o sha vai
        para known_files e a reconciliação nunca o re-oferece (§9.6)."""
        project = wp.Project.create(self.tmp / "p")
        old = make_loc(project.root / "input" / "enGB_1.3.2.json", EN_TEXTS)
        project.set_input(old)
        new = make_loc(project.root / "input" / "enGB_1.6.1.514.json",
                       {**EN_TEXTS, "uuid-en-6": "A brand new string here."})
        project.set_input(new)  # substitui: sha antigo vira "conhecido"
        self.assertEqual(project.state["input"]["file"],
                         "input/enGB_1.6.1.514.json")
        self.assertIn(wp.sha256_of_file(old),
                      project.state["known_files"])
        # O dump antigo continua em input/ mas NÃO é oferecido de novo.
        self.assertTrue(old.is_file())
        self.assertEqual(project.reconcile()["untracked"], [])


class TestGlossaryCount(TempDirCase):
    def test_count_terms(self):
        gloss = self.tmp / "glossary.json"
        gloss.write_text(json.dumps({"metadata": {}, "terms": [{}, {}, {}]}),
                         encoding="utf-8")
        self.assertEqual(wp.count_glossary_terms(gloss), 3)

    def test_count_terms_invalid(self):
        gloss = self.tmp / "glossary.json"
        gloss.write_text("{}", encoding="utf-8")
        with self.assertRaises(wp.ProjectError):
            wp.count_glossary_terms(gloss)


class TestVersionedPaths(TempDirCase):
    """Convenção de nomes versionados (§2, revisão 2026-07-25)."""

    def test_track_target_versioned_suggestion(self):
        project = wp.Project.create(self.tmp / "p")
        # Sem versão: nome plano de fallback.
        self.assertEqual(project.track_target(wp.TRACK_PRESERVED).name,
                         "ptBR_preserved.json")
        project.set_game_version("1.6.1.514")
        self.assertEqual(project.track_target(wp.TRACK_PRESERVED).name,
                         "ptBR_preserved_1.6.1.514.json")
        self.assertEqual(project.track_target(wp.TRACK_FULL).name,
                         "ptBR_full_1.6.1.514.json")

    def test_track_path_prefers_registered_then_legacy(self):
        project = wp.Project.create(self.tmp / "p")
        self.assertIsNone(project.track_path(wp.TRACK_FULL))
        # Legado: nome canônico em disco, sem tracks.file → fallback.
        legacy = make_loc(project.root / "output" / "ptBR_full.json",
                          PT_FULL_TEXTS)
        self.assertEqual(project.track_path(wp.TRACK_FULL), legacy)
        # Registrado ganha do legado.
        versioned = make_loc(
            project.root / "output" / "ptBR_full_1.6.1.514.json",
            PT_FULL_TEXTS)
        project.set_track_file(wp.TRACK_FULL, versioned)
        self.assertEqual(project.track_path(wp.TRACK_FULL), versioned)

    def test_track_target_keeps_existing_master(self):
        """--resume continua escrevendo no MESMO master registrado."""
        project = wp.Project.create(self.tmp / "p")
        master = make_loc(project.root / "output" / "ptBR_preserved.json",
                          PT_PRESERVED_TEXTS)
        project.set_game_version("1.6.1.514")
        # Master legado existe → alvo é ele, não um arquivo novo versionado.
        self.assertEqual(project.track_target(wp.TRACK_PRESERVED), master)
        project.set_track_file(wp.TRACK_PRESERVED, master)
        self.assertEqual(project.track_target(wp.TRACK_PRESERVED), master)

    def test_set_track_file_outside_project_raises(self):
        project = wp.Project.create(self.tmp / "p")
        outside = make_loc(self.tmp / "ptBR_full.json", PT_FULL_TEXTS)
        with self.assertRaises(wp.ProjectError):
            project.set_track_file(wp.TRACK_FULL, outside)

    def test_rename_files_to_version(self):
        project = wp.Project.create(self.tmp / "p")
        en = make_loc(project.root / "input" / "enGB_1.3.2.json", EN_TEXTS)
        pres = make_loc(project.root / "output" / "ptBR_preserved.json",
                        PT_PRESERVED_TEXTS)
        full = make_loc(
            project.root / "output" / "ptBR_full_1.3.2.json",
            PT_FULL_TEXTS)
        project.set_input(en)
        project.set_track_file(wp.TRACK_PRESERVED, pres)
        project.set_track_file(wp.TRACK_FULL, full)

        renamed = project.rename_files_to_version("1.6.1.514",
                                                  include_input=True)
        self.assertEqual(len(renamed), 3)
        self.assertEqual(project.state["input"]["file"],
                         "input/enGB_1.6.1.514.json")
        self.assertEqual(project.state["tracks"]["preserved"]["file"],
                         "output/ptBR_preserved_1.6.1.514.json")
        self.assertEqual(project.state["tracks"]["full"]["file"],
                         "output/ptBR_full_1.6.1.514.json")
        self.assertFalse(pres.is_file())
        self.assertTrue((project.root / "output"
                         / "ptBR_preserved_1.6.1.514.json").is_file())
        # Rename para a MESMA versão é no-op silencioso.
        self.assertEqual(project.rename_files_to_version("1.6.1.514",
                                                         include_input=True),
                         [])

    def test_rename_skips_missing_files_silently(self):
        project = wp.Project.create(self.tmp / "p")
        self.assertEqual(project.rename_files_to_version("1.6.1.514"), [])

    def test_rename_invalid_version_raises(self):
        project = wp.Project.create(self.tmp / "p")
        with self.assertRaises(wp.ProjectError):
            project.rename_files_to_version("1.6-beta")

    def test_legacy_project_still_works(self):
        """Projeto antigo (nomes canônicos planos, sem tracks.file):
        fallback resolve os caminhos e reconcile não re-oferece."""
        project = wp.Project.create(self.tmp / "p")
        legacy = make_loc(project.root / "output" / "ptBR_full.json",
                          PT_FULL_TEXTS)
        # Simula project.json antigo: done, sem campo "file".
        project.state["tracks"][wp.TRACK_FULL] = {
            "status": wp.TRACK_STATUS_DONE, "updated": "2026-07-01",
            "translated": len(PT_FULL_TEXTS), "skipped_free": 0}
        project.save()
        self.assertEqual(project.track_path(wp.TRACK_FULL), legacy)
        self.assertEqual(project.track_target(wp.TRACK_FULL), legacy)
        self.assertTrue(project.has_any_output())
        self.assertEqual(project.reconcile()["untracked"], [])
        self.assertEqual(project.cleanup_stale(), [])
        # Bump explícito migra o nome para o versionado.
        renamed = project.rename_files_to_version("1.6.1.514")
        self.assertEqual(renamed, [("ptBR_full.json",
                                    "ptBR_full_1.6.1.514.json")])


if __name__ == "__main__":
    unittest.main()
