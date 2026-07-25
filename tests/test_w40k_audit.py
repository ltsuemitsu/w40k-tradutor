"""Testes do módulo de auditoria (w40k_audit.py) — Fase 4.

Stdlib-only: roda sem PySide6 com `python -m unittest discover -s tests`.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

try:
    import _isolate  # noqa: F401 — isola W40K_CONFIG_DIR (flat discovery)
except ImportError:
    pass  # modo pacote: tests/__init__.py já isolou

import w40k_audit as au
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


EN_TEXTS = {
    "u-ok": "The voidship drifts through the darkness.",
    "u-fail": "This weapon deals massive damage to enemies.",
    "u-ident": "You have acquired a new talent for your hero.",
    "u-suspect": "The captain orders you to defend the ship.",
    "u-leak": "The Plasma Gun deals {mf|his|her} damage.",
    "u-preserved": "Plasma Gun",
    "u-skip": "placeholder",
}

PT_ENTRIES = {
    "u-ok": "A nave à deriva atravessa a escuridão.",
    "u-fail": {"Text": "This weapon deals massive damage to enemies.",
               "_failed": True},
    # Idêntica ao EN, >10 chars → Idênticas.
    "u-ident": "You have acquired a new talent for your hero.",
    # PT com acento + ≥2 palavras EN comuns → Suspeita (meio-tradução).
    "u-suspect": "O capitão ordena that you defenda the ship.",
    # Placeholder vazado → Suspeita (varredura extra do w40k_audit).
    "u-leak": "A Arma de Plasma causa {mf|his|her} dano.",
    "u-preserved": {"Text": "Plasma Gun", "_preserved": True},
    "u-skip": {"Text": "placeholder", "_skipped": "placeholder"},
}


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="w40k_au_test_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.project = wp.Project.create(self.tmp / "proj")
        make_loc(self.project.root / "input" / "enGB.json", EN_TEXTS)
        self.project.state["input"] = {
            "file": "input/enGB.json", "original_name": "enGB.json",
            "sha256": "x", "strings": len(EN_TEXTS)}
        self.project.save()
        make_loc(self.project.output_path(wp.TRACK_PRESERVED), PT_ENTRIES)


class TestAuditCategories(TempDirCase):
    def test_three_categories(self):
        report = au.audit_output(
            self.project.output_path(wp.TRACK_PRESERVED),
            self.project.root / "input" / "enGB.json")
        counts = report["counts"]
        self.assertEqual(counts["failed"], 1)     # u-fail (_failed)
        self.assertEqual(counts["identical"], 1)  # u-ident (EN == PT)
        self.assertEqual(counts["suspect"], 2)    # u-suspect + u-leak
        cats = {r["uuid"]: r["category"] for r in report["rows"]}
        self.assertEqual(cats["u-fail"], "failed")
        self.assertEqual(cats["u-ident"], "identical")
        self.assertEqual(cats["u-suspect"], "suspect")
        self.assertEqual(cats["u-leak"], "suspect")
        self.assertEqual(cats["u-leak"] and
                         report["rows"][[r["uuid"] for r in report["rows"]]
                                        .index("u-leak")]["reason"],
                         "placeholder_vazou")
        # Linhas trazem EN × PT completos para a tabela.
        row = next(r for r in report["rows"] if r["uuid"] == "u-fail")
        self.assertEqual(row["en"], EN_TEXTS["u-fail"])
        self.assertEqual(row["pt"], PT_ENTRIES["u-fail"]["Text"])

    def test_preserved_and_skipped_ignored(self):
        report = au.audit_output(
            self.project.output_path(wp.TRACK_PRESERVED),
            self.project.root / "input" / "enGB.json")
        uuids = {r["uuid"] for r in report["rows"]}
        self.assertNotIn("u-preserved", uuids)
        self.assertNotIn("u-skip", uuids)
        self.assertNotIn("u-ok", uuids)

    def test_missing_input_gate(self):
        (self.project.root / "input" / "enGB.json").unlink()
        with self.assertRaises(wp.ProjectError) as ctx:
            au.audit_output(self.project.output_path(wp.TRACK_PRESERVED),
                            self.project.root / "input" / "enGB.json")
        self.assertIn("input", str(ctx.exception))

    def test_run_audit_writes_report_and_state(self):
        report = au.run_audit(self.project, wp.TRACK_PRESERVED)
        self.assertTrue(report["report_path"].is_file())
        self.assertIn("_audit_preserved.json", report["report_path"].name)
        state = json.loads(
            (self.project.root / "project.json").read_text(encoding="utf-8"))
        audit = state["last_audit"]
        self.assertEqual(audit["failed"], 1)
        self.assertEqual(audit["identical"], 1)
        self.assertEqual(audit["suspect"], 2)
        self.assertTrue(audit["date"])


class TestRetry(TempDirCase):
    def test_write_retry_uuids(self):
        path = au.write_retry_uuids(self.project, ["u-fail", "u-leak"])
        self.assertIn("_retry_uuids.json", path.name)
        data = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(data, ["u-fail", "u-leak"])
        with self.assertRaises(wp.ProjectError):
            au.write_retry_uuids(self.project, [])

    def test_build_retry_args_preserved(self):
        args = au.build_retry_args(Path("tradutor.py"), self.project,
                                   wp.TRACK_PRESERVED,
                                   Path("audit/retry.json"),
                                   "deepseek-v4-flash", Path("glossary.json"))
        self.assertEqual(args[args.index("--mode") + 1], "preserve")
        self.assertIn("--resume", args)
        self.assertIn("--retranslate-map", args)
        self.assertIn("--preserve-map", args)
        self.assertEqual(args[args.index("--model") + 1],
                         "deepseek-v4-flash")

    def test_build_retry_args_full_uses_complete_mode(self):
        args = au.build_retry_args(Path("tradutor.py"), self.project,
                                   wp.TRACK_FULL, Path("retry.json"),
                                   "glm-5.2", None)
        self.assertEqual(args[args.index("--mode") + 1], "complete")
        self.assertNotIn("--preserve-map", args)
        self.assertNotIn("-g", args)

    def test_build_retry_args_carries_effective_profile_flags(self):
        """Overrides de workers/save_every das Configurações chegam ao engine
        via -w/--save-every explícitos (Issue 1)."""
        import os
        import w40k_settings as st
        old = os.environ.get("W40K_CONFIG_DIR")
        os.environ["W40K_CONFIG_DIR"] = str(self.tmp / "cfg")
        try:
            st.set_profile_override("deepseek-v4-flash",
                                    {"workers": 12, "save_every": 9})
            args = au.build_retry_args(Path("tradutor.py"), self.project,
                                       wp.TRACK_PRESERVED,
                                       Path("audit/retry.json"),
                                       "deepseek-v4-flash",
                                       Path("glossary.json"))
            self.assertEqual(args[args.index("-w") + 1], "12")
            self.assertEqual(args[args.index("--save-every") + 1], "9")
            # Sem override → padrões de código do perfil (flash: 8/8).
            st.reset_profile_overrides("deepseek-v4-flash")
            args = au.build_retry_args(Path("tradutor.py"), self.project,
                                       wp.TRACK_PRESERVED,
                                       Path("audit/retry.json"),
                                       "deepseek-v4-flash",
                                       Path("glossary.json"))
            self.assertEqual(args[args.index("-w") + 1], "8")
            self.assertEqual(args[args.index("--save-every") + 1], "8")
        finally:
            if old is None:
                os.environ.pop("W40K_CONFIG_DIR", None)
            else:
                os.environ["W40K_CONFIG_DIR"] = old

    def test_mark_for_retry_flags_and_backs_up(self):
        output = self.project.output_path(wp.TRACK_PRESERVED)
        before = output.stat().st_size
        result = au.mark_for_retry(self.project, wp.TRACK_PRESERVED,
                                   ["u-ident", "u-leak"])
        self.assertEqual(result["marked"], 2)
        self.assertTrue(result["backup"].is_file())
        self.assertIn("_pre-merge_ptBR_preserved.json",
                      result["backup"].name)
        data = json.loads(output.read_text(encoding="utf-8"))
        self.assertTrue(data["strings"]["u-ident"]["_failed"])
        self.assertTrue(data["strings"]["u-leak"]["_failed"])
        self.assertNotEqual(output.stat().st_size, before)


class TestMergeWithBackup(TempDirCase):
    def test_manual_edit_merge(self):
        output = self.project.output_path(wp.TRACK_PRESERVED)
        result = au.merge_with_backup(
            self.project, wp.TRACK_PRESERVED,
            {"u-suspect": "O capitão ordena que você defenda a nave."})
        self.assertEqual(result["changed"], 1)
        self.assertTrue(result["backup"].is_file())
        data = json.loads(output.read_text(encoding="utf-8"))
        self.assertEqual(data["strings"]["u-suspect"]["Text"],
                         "O capitão ordena que você defenda a nave.")

    def test_merge_clears_failed_flag(self):
        au.merge_with_backup(self.project, wp.TRACK_PRESERVED,
                             {"u-fail": "Esta arma causa dano massivo."})
        data = json.loads(
            self.project.output_path(wp.TRACK_PRESERVED)
            .read_text(encoding="utf-8"))
        self.assertNotIn("_failed", data["strings"]["u-fail"])

    def test_merge_skips_empty_and_missing(self):
        with self.assertRaises(wp.ProjectError):
            au.merge_with_backup(self.project, wp.TRACK_PRESERVED,
                                 {"u-ok": "   "})
        with self.assertRaises(wp.ProjectError):
            au.merge_with_backup(self.project, wp.TRACK_PRESERVED,
                                 {"uuid-inexistente": "texto"})


class TestReleaseGate(TempDirCase):
    def test_blocked_when_never_audited(self):
        decision, reason = au.release_gate_decision(None, [time.time()])
        self.assertEqual(decision, au.GATE_BLOCKED)
        self.assertIn("nunca executada", reason)

    def test_blocked_when_output_newer(self):
        audit = {"date": "2026-07-25T10:00:00",
                 "failed": 0, "identical": 0, "suspect": 0}
        newer = datetime(2026, 7, 25, 12, 0, 0).timestamp()
        decision, reason = au.release_gate_decision(audit, [newer])
        self.assertEqual(decision, au.GATE_BLOCKED)
        self.assertIn("mudaram desde a última auditoria", reason)

    def test_warn_with_pending_issues(self):
        audit = {"date": "2026-07-25T10:00:00",
                 "failed": 12, "identical": 340, "suspect": 88}
        older = datetime(2026, 7, 25, 9, 0, 0).timestamp()
        decision, reason = au.release_gate_decision(audit, [older])
        self.assertEqual(decision, au.GATE_WARN)
        self.assertIn("12 falhas", reason)
        self.assertIn("88 suspeitas", reason)

    def test_ok_clean_and_identical_only(self):
        older = datetime(2026, 7, 25, 9, 0, 0).timestamp()
        clean = {"date": "2026-07-25T10:00:00",
                 "failed": 0, "identical": 0, "suspect": 0}
        self.assertEqual(au.release_gate_decision(clean, [older])[0],
                         au.GATE_OK)
        ident = {"date": "2026-07-25T10:00:00",
                 "failed": 0, "identical": 340, "suspect": 0}
        decision, reason = au.release_gate_decision(ident, [older])
        self.assertEqual(decision, au.GATE_OK)  # idênticas não bloqueiam
        self.assertIn("340", reason)

    def test_date_only_schema_not_stale_same_day(self):
        # Schema antigo (date-only): auditoria do mesmo dia não é velha.
        audit = {"date": "2026-07-25", "failed": 0, "suspect": 0}
        same_day_morning = datetime(2026, 7, 25, 8, 0, 0).timestamp()
        decision, _ = au.release_gate_decision(audit, [same_day_morning])
        self.assertEqual(decision, au.GATE_OK)


if __name__ == "__main__":
    unittest.main()
