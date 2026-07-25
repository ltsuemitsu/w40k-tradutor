"""Testes do módulo de Dia de Patch (w40k_patch.py) — Fase 5.

Stdlib-only: roda sem PySide6 com `python -m unittest discover -s tests`.
"""

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import _isolate  # noqa: F401 — isola W40K_CONFIG_DIR (flat discovery)
except ImportError:
    pass  # modo pacote: tests/__init__.py já isolou

import w40k_patch as pch
import w40k_preflight as pf
import w40k_project as wp


def make_loc(path: Path, entries: dict) -> Path:
    """entries: {uuid: texto} ou {uuid: {"Text": t, flags...}}."""
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


OLD_EN = {
    "u-keep": "The voidship drifts through the darkness.",
    "u-num": "Damage: 10",
    "u-char": "A",
    "u-word": "Open the door",
    "u-move": "Plasma Gun",
    "u-gone": "This will vanish entirely.",
    "u-empty": "This will be emptied.",
}

NEW_EN = {
    "u-keep": "The voidship drifts through the darkness.",
    "u-num": "Damage: 12",          # número modificado
    "u-char": "B",                  # caractere único modificado
    "u-word": "Open the gate",      # palavra modificada
    "u-new": "A brand new string appears.",
    "u-move2": "Plasma Gun",        # movida: texto idêntico, UUID novo
    "u-empty": "",                  # esvaziada pelo patch
    # u-gone ausente → removida
}

PT_MASTER = {
    "u-keep": "A nave à deriva atravessa a escuridão.",
    "u-num": "Dano: 10",
    "u-char": "A",
    "u-word": "Abra a porta",
    "u-move": {"Text": "Plasma Gun", "_preserved": True},
    "u-gone": "Isso vai sumir.",
    "u-empty": "Isso será esvaziado.",
    "u-meta": {"Text": "Entrada com lixo", "_issue": "validator antigo"},
}

DELTA_PT = {
    "u-new": {"Text": "Uma string novinha aparece.", "_status": "new"},
    "u-num": {"Text": "Dano: 12", "_status": "modified",
              "_old_text": "Damage: 10"},
    "u-char": "B",
    "u-word": {"Text": "Abra o portão", "_status": "modified",
               "_old_text": "Open the door"},
    "u-void": "",                    # vazio → ignorado (semântica merge.py)
}


class TempProjectCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="w40k_pch_test_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.project = wp.Project.create(self.tmp / "proj")
        self.old_path = make_loc(self.project.root / "input" / "enGB.json",
                                 OLD_EN)
        self.project.state["input"] = {
            "file": "input/enGB.json", "original_name": "enGB.json",
            "sha256": "x", "strings": len(OLD_EN)}
        self.project.save()
        make_loc(self.project.output_path(wp.TRACK_PRESERVED), PT_MASTER)
        self.new_path = make_loc(self.tmp / "enGB_1.7.0.json", NEW_EN)
        self.old_data = wp.load_localization(self.old_path)
        self.new_data = wp.load_localization(self.new_path)
        self.pt_data = wp.load_localization(
            self.project.output_path(wp.TRACK_PRESERVED))
        self.preview = pch.categorize_patch(
            self.old_data, self.new_data, self.pt_data)

    def make_delta_pt(self, entries=None) -> Path:
        path = pch.delta_pt_path(self.project)
        make_loc(path, entries if entries is not None else DELTA_PT)
        return path


class TestCategorize(TempProjectCase):
    def test_counts_per_category(self):
        p = self.preview
        self.assertEqual(len(p["new"]), 1)
        self.assertEqual(len(p["modified"]), 3)
        self.assertEqual(len(p["moved"]), 1)
        self.assertEqual(len(p["removed"]), 1)
        self.assertEqual(len(p["emptied"]), 1)
        self.assertEqual(p["unchanged"], 1)
        self.assertEqual(p["changed"], 7)
        self.assertEqual(p["total_new_dump"], len(NEW_EN))

    def test_modification_regression_number_char_word(self):
        mods = {uid: (new, old) for uid, new, old in self.preview["modified"]}
        self.assertEqual(mods["u-num"], ("Damage: 12", "Damage: 10"))
        self.assertEqual(mods["u-char"], ("B", "A"))
        self.assertEqual(mods["u-word"], ("Open the gate", "Open the door"))

    def test_moved_maps_old_to_new_with_pt(self):
        moved = self.preview["moved"][0]
        self.assertEqual(moved[0], "u-move")
        self.assertEqual(moved[1], "u-move2")
        self.assertEqual(moved[2], "Plasma Gun")
        self.assertEqual(moved[3], "Plasma Gun")  # PT existente p/ carregar

    def test_emptied_detected(self):
        self.assertEqual(self.preview["emptied"],
                         [("u-empty", "This will be emptied.")])

    def test_removed_excludes_moved(self):
        self.assertEqual([u for u, _ in self.preview["removed"]], ["u-gone"])


class TestDelta(TempProjectCase):
    def test_delta_has_only_new_and_modified(self):
        delta = pch.build_delta(self.preview, self.new_data)
        strings = delta["strings"]
        self.assertEqual(set(strings),
                         {"u-new", "u-num", "u-char", "u-word"})
        self.assertEqual(strings["u-new"]["_status"], "new")
        self.assertEqual(strings["u-num"]["_status"], "modified")
        self.assertEqual(strings["u-num"]["_old_text"], "Damage: 10")
        # Movida NÃO entra no delta pago (fix 2).
        self.assertNotIn("u-move2", strings)

    def test_write_delta_paths(self):
        delta = pch.build_delta(self.preview, self.new_data)
        path = pch.write_delta(self.project, delta)
        self.assertTrue(path.is_file())
        self.assertEqual(path.parent.name, "patches")
        self.assertTrue(path.name.endswith("_delta.json"))
        self.assertEqual(pch.delta_pt_path(self.project).name,
                         path.name.replace("_delta.json", "_delta_pt.json"))

    def test_cost_only_for_delta(self):
        """Pré-voo sobre o delta conta SÓ as strings pagas."""
        delta = pch.build_delta(self.preview, self.new_data)
        path = pch.write_delta(self.project, delta)
        result = pf.run_preflight(path, None)
        self.assertEqual(result.total, 4)  # 1 nova + 3 modificadas
        # Movidas/removidas/esvaziadas/intactas não custam nada.

    def test_build_delta_args_preserve_map(self):
        args = pch.build_delta_args(
            Path("tradutor.py"), self.project,
            pch.delta_path(self.project), pch.delta_pt_path(self.project),
            "deepseek-v4-flash", None)
        joined = " ".join(args)
        self.assertIn("--mode preserve", joined)
        self.assertIn("--resume", joined)
        self.assertIn("--preserve-map", joined)  # Preservada existe
        self.assertNotIn("-g", joined)

    def test_build_delta_args_glossary(self):
        args = pch.build_delta_args(
            Path("tradutor.py"), self.project,
            pch.delta_path(self.project), pch.delta_pt_path(self.project),
            "deepseek-v4-flash", Path("glossary.json"))
        self.assertIn("-g", args)

    def test_build_delta_args_carries_effective_profile_flags(self):
        """Delta run também honra overrides de workers/save_every (Issue 1)."""
        import os
        import w40k_settings as st
        old = os.environ.get("W40K_CONFIG_DIR")
        os.environ["W40K_CONFIG_DIR"] = str(self.tmp / "cfg")
        try:
            st.set_profile_override("glm-5.2",
                                    {"workers": 5, "save_every": 2})
            args = pch.build_delta_args(
                Path("tradutor.py"), self.project,
                pch.delta_path(self.project), pch.delta_pt_path(self.project),
                "glm-5.2", None)
            self.assertEqual(args[args.index("-w") + 1], "5")
            self.assertEqual(args[args.index("--save-every") + 1], "2")
        finally:
            if old is None:
                os.environ.pop("W40K_CONFIG_DIR", None)
            else:
                os.environ["W40K_CONFIG_DIR"] = old


class TestRegisterNewInput(TempProjectCase):
    def test_archive_and_canonical_updated(self):
        info = pch.register_new_input(self.project, self.new_path)
        self.assertTrue(info["archive"].is_file())
        self.assertEqual(info["archive"].name, "enGB_1.7.0.json")
        self.assertEqual(info["version"], "1.7.0")
        # Canonical agora é o dump novo.
        canonical = wp.load_localization(self.project.input_path())
        self.assertIn("u-new", canonical["strings"])
        self.assertEqual(self.project.state["input"]["strings"], len(NEW_EN))
        self.assertEqual(self.project.state["game_version"], "1.7.0")
        # Arquivo antigo continua em input/ (nada é movido/destruído).

    def test_archive_fallback_date_name(self):
        plain = self.tmp / "dump_sem_versao.json"
        shutil.copy2(self.new_path, plain)
        info = pch.register_new_input(self.project, plain)
        self.assertIsNone(info["version"])
        self.assertRegex(info["archive"].name,
                         r"^enGB_\d{4}-\d{2}-\d{2}\.json$")

    def test_blocked_without_prior_input(self):
        empty = wp.Project.create(self.tmp / "proj_vazio")
        with self.assertRaises(wp.ProjectError):
            pch.register_new_input(empty, self.new_path)


class TestMergePatch(TempProjectCase):
    def test_merge_without_cleanup(self):
        delta_pt = self.make_delta_pt()
        stats = pch.merge_patch(self.project, wp.TRACK_PRESERVED,
                                delta_pt, self.preview, cleanup=False)
        self.assertTrue(stats["backup"].is_file())
        self.assertEqual(stats["backup"].parent.name, "backups")
        self.assertEqual(stats["moved"], 1)
        self.assertEqual(stats["upserted"], 4)
        self.assertEqual(stats["skipped_empty"], 1)
        self.assertEqual(stats["cleaned"], 0)

        strings = wp.load_localization(
            self.project.output_path(wp.TRACK_PRESERVED))["strings"]
        # Movida: PT viajou grátis (flags preservadas), UUID antigo saiu.
        self.assertEqual(strings["u-move2"]["Text"], "Plasma Gun")
        self.assertTrue(strings["u-move2"]["_preserved"])
        self.assertNotIn("u-move", strings)
        # Delta aplicado.
        self.assertEqual(strings["u-num"]["Text"], "Dano: 12")
        self.assertEqual(strings["u-new"]["Text"],
                         "Uma string novinha aparece.")
        # Sem limpeza: removida e esvaziada continuam no master.
        self.assertIn("u-gone", strings)
        self.assertIn("u-empty", strings)

    def test_merge_with_cleanup(self):
        delta_pt = self.make_delta_pt()
        stats = pch.merge_patch(self.project, wp.TRACK_PRESERVED,
                                delta_pt, self.preview, cleanup=True)
        self.assertEqual(stats["cleaned"], 2)  # u-gone + u-empty
        strings = wp.load_localization(
            self.project.output_path(wp.TRACK_PRESERVED))["strings"]
        self.assertNotIn("u-gone", strings)
        self.assertNotIn("u-empty", strings)

    def test_metadata_never_reaches_master(self):
        delta_pt = self.make_delta_pt()
        pch.merge_patch(self.project, wp.TRACK_PRESERVED,
                        delta_pt, self.preview, cleanup=True)
        strings = wp.load_localization(
            self.project.output_path(wp.TRACK_PRESERVED))["strings"]
        for uuid, entry in strings.items():
            for key in pch.STRIP_KEYS:
                self.assertNotIn(key, entry, f"{uuid} ainda tem {key}")
        # O lixo pré-existente (u-meta._issue) também foi removido.
        self.assertEqual(strings["u-meta"], {"Offset": 112,
                                             "Text": "Entrada com lixo"})

    def test_backup_created_before_merge(self):
        delta_pt = self.make_delta_pt()
        stats = pch.merge_patch(self.project, wp.TRACK_PRESERVED,
                                delta_pt, self.preview)
        backup = wp.load_localization(stats["backup"])["strings"]
        # Backup guarda o estado ANTES do merge.
        self.assertEqual(backup["u-num"]["Text"], "Dano: 10")
        self.assertIn("u-move", backup)

    def test_missing_output_raises(self):
        delta_pt = self.make_delta_pt()
        with self.assertRaises(wp.ProjectError):
            pch.merge_patch(self.project, wp.TRACK_FULL,
                            delta_pt, self.preview)


class TestUpdateProject(TempProjectCase):
    def test_tracks_and_patch_entry(self):
        delta_pt = self.make_delta_pt()
        pch.merge_patch(self.project, wp.TRACK_PRESERVED,
                        delta_pt, self.preview, cleanup=True)
        pch.update_project_after_patch(
            self.project, "1.7.0", self.preview, [wp.TRACK_PRESERVED])
        entry = self.project.state["tracks"][wp.TRACK_PRESERVED]
        self.assertEqual(entry["status"], wp.TRACK_STATUS_DONE)
        # Bump de versão (§2): master renomeado p/ ptBR_preserved_1.7.0.json.
        self.assertEqual(entry["file"], "output/ptBR_preserved_1.7.0.json")
        new_master = self.project.track_path(wp.TRACK_PRESERVED)
        self.assertEqual(new_master.name, "ptBR_preserved_1.7.0.json")
        self.assertTrue(new_master.is_file())
        counts = pf.summarize_output(new_master)
        self.assertEqual(entry["translated"], counts["translated"])
        patches = self.project.state["patches"]
        self.assertEqual(len(patches), 1)
        self.assertEqual(patches[0]["version"], "1.7.0")
        self.assertEqual(patches[0]["new"], 1)
        self.assertEqual(patches[0]["modified"], 3)
        self.assertEqual(patches[0]["moved"], 1)
        self.assertEqual(patches[0]["removed"], 1)
        self.assertEqual(patches[0]["emptied"], 1)


if __name__ == "__main__":
    unittest.main()
