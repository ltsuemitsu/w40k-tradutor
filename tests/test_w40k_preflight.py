"""Testes do módulo de Pré-Voo (w40k_preflight.py) — Fase 2.

Stdlib-only: roda sem PySide6 e sem rede com
`python -m unittest discover -s tests`.
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

import w40k_preflight as pf
import w40k_project as wp


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


def make_glossary(path: Path, terms: list) -> Path:
    path.write_text(json.dumps(
        {"metadata": {"version": "2.1"}, "terms": terms},
        ensure_ascii=False), encoding="utf-8")
    return path


GLOSS_TERMS = [
    {"term_english": "Plasma Gun", "term_translated": "Plasma Gun",
     "category": "weapon", "preserve": True},
    {"term_english": "Weapon Skill", "term_translated": "Weapon Skill",
     "category": "skill", "preserve": True},
    # "location" NÃO está nas preserve-cats: entra na cobertura mas não
    # vira exact/inline no modo preserve.
    {"term_english": "Voidship", "term_translated": "Nave do Vazio",
     "category": "location", "preserve": False},
]

# Fixture pequena e previsível:
#  - 1 placeholder (skip)        → "u-skip"
#  - 1 EULA (>15000 chars)       → "u-eula"
#  - 1 exact EN (glossário)      → "u-exact"
#  - 1 inline (termo embutido)   → "u-inline"
#  - 3 limpas para a API         → "u-api-1..3"
# api_bound = u-inline + u-api-1..3 = 4 (inline também vai para a API).
API_KEYS = ("u-inline", "u-api-1", "u-api-2", "u-api-3")
FIXTURE_TEXTS = {
    "u-skip": "placeholder",
    "u-eula": "license agreement " * 1000,  # ~19.000 chars → EULA
    "u-exact": "Plasma Gun",
    "u-inline": "Your Plasma Gun overheats after every shot in combat.",
    "u-api-1": "The Voidship drifts through the darkness of the Koronus "
               "Expanse and the crew whispers in fear.",
    "u-api-2": "You have acquired a new destiny for your Rogue Trader "
               "and the Voidship answers your command.",
    "u-api-3": "Voidship Voidship Voidship — the Voidmaster repeated the "
               "word four times, and the Voidship groaned.",
}


class TempDirCase(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="w40k_pf_test_"))
        self.addCleanup(lambda: shutil.rmtree(self.tmp, ignore_errors=True))
        self.input = make_loc(self.tmp / "enGB.json", FIXTURE_TEXTS)
        self.gloss = make_glossary(self.tmp / "glossary.json", GLOSS_TERMS)


class TestPreflightCounts(TempDirCase):
    def test_classification_buckets(self):
        r = pf.run_preflight(self.input, self.gloss, model="deepseek-v4-flash")
        self.assertEqual(r.total, 7)
        self.assertEqual(r.skip_placeholder, 1)
        self.assertEqual(r.skip_eula, 1)
        self.assertEqual(r.exact_preserved, 1)
        self.assertEqual(r.inline_locked, 1)
        self.assertEqual(r.api_bound, 4)
        self.assertEqual(r.free_total, 3)

    def test_without_glossary_everything_goes_to_api(self):
        r = pf.run_preflight(self.input, None)
        self.assertEqual(r.exact_preserved, 0)
        self.assertEqual(r.inline_locked, 0)
        self.assertEqual(r.api_bound, 5)  # 7 - skip - eula
        self.assertIsNone(r.coverage)

    def test_token_estimate_heuristic(self):
        r = pf.run_preflight(self.input, self.gloss)
        expected = sum(max(1, len(FIXTURE_TEXTS[k]) // 4) for k in API_KEYS)
        self.assertEqual(r.input_tokens_est, expected)
        self.assertEqual(r.output_tokens_est, expected)

    def test_workers_and_batches_from_profile(self):
        r = pf.run_preflight(self.input, self.gloss, model="deepseek-v4-flash")
        self.assertEqual(r.workers, 8)  # perfil deepseek-v4-flash
        self.assertGreaterEqual(r.batches_est, 1)
        self.assertIn("bulk", r.cost_hint)
        self.assertIn("estimativa grosseira", r.duration_hint)

    def test_recalc_estimate_on_model_switch(self):
        r = pf.run_preflight(self.input, self.gloss, model="deepseek-v4-flash")
        tokens_before = r.input_tokens_est
        pf.recalc_estimate(r, "glm-5.2")
        self.assertEqual(r.workers, 3)          # perfil glm-5.2
        self.assertEqual(r.model, "glm-5.2")
        self.assertIn("premium", r.cost_hint)
        self.assertEqual(r.input_tokens_est, tokens_before)  # inalterado

    def test_list_models_and_provider(self):
        models = pf.list_models()
        self.assertTrue(models)
        ids = [m[0] for m in models]
        self.assertIn("deepseek-v4-flash", ids)
        self.assertEqual(pf.provider_for_model("deepseek-v4-flash"),
                         "DeepSeek")
        self.assertEqual(pf.provider_for_model("glm-5.2"), "Zhipu GLM")

    def test_quality_model_cost_hint(self):
        r = pf.run_preflight(self.input, self.gloss, model="glm-5.2")
        self.assertEqual(r.workers, 3)
        self.assertIn("premium", r.cost_hint)

    def test_coverage_computation(self):
        r = pf.run_preflight(self.input, self.gloss)
        # As 3 strings da API contêm "Voidship" (termo do glossário).
        self.assertIsNotNone(r.coverage)
        self.assertAlmostEqual(r.coverage, 1.0)
        self.assertEqual(r.coverage_terms, len(GLOSS_TERMS))

    def test_candidates_finds_repeated_unknown_terms(self):
        r = pf.run_preflight(self.input, self.gloss)
        cand = dict(r.candidates)
        # "Voidship" já está no glossário → não pode aparecer.
        self.assertNotIn("Voidship", cand)
        # "Rogue Trader" aparece 1× (< min_count) e "Koronus Expanse" 1×.
        # "Voidmaster" 1× — fixture pequena; o scanner deve ao menos rodar.
        self.assertIsInstance(r.candidates, list)

    def test_candidates_scanner_directly(self):
        texts = [
            "The Star Port welcomes the Rogue Trader.",
            "Every Star Port in the Expanse knows your name.",
            "A third Star Port, abandoned and dark.",
        ]
        result = pf.scan_candidate_terms(texts, glossary_keys=set(),
                                         min_count=3)
        self.assertIn(("Star Port", 3), result)

    def test_candidates_respects_glossary_and_stopwords(self):
        texts = ["The Plasma Gun hums. The Plasma Gun sings. "
                 "The Plasma Gun waits. The The The."]
        result = pf.scan_candidate_terms(
            texts, glossary_keys={"plasma gun"}, min_count=2)
        terms = [t for t, _ in result]
        self.assertNotIn("Plasma Gun", terms)
        self.assertNotIn("The", terms)

    def test_candidates_drops_contractions_and_discourse(self):
        texts = [
            "It's fine. It's fine. It's fine. "
            "I'll go. I'll go. I'll go. "
            "However the Void Blade cuts. However the Void Blade cuts. "
            "However the Void Blade cuts. "
            "Whenever you fire. Whenever you fire. Whenever you fire.",
        ]
        result = pf.scan_candidate_terms(texts, glossary_keys=set(), min_count=3)
        terms = [t for t, _ in result]
        self.assertNotIn("It's", terms)
        self.assertNotIn("I'll", terms)
        self.assertNotIn("However", terms)
        self.assertNotIn("Whenever", terms)
        self.assertIn("Void Blade", terms)

    def test_candidates_strips_encyclopedia_keys(self):
        texts = [
            "Deals {g|Encyclopedia:DamageGlossary}damage{/g}.",
            "Deals {g|Encyclopedia:DamageGlossary}damage{/g}.",
            "Deals {g|Encyclopedia:DamageGlossary}damage{/g}.",
            "The Star Port opens. The Star Port opens. The Star Port opens.",
        ]
        result = pf.scan_candidate_terms(texts, glossary_keys=set(), min_count=3)
        terms = [t for t, _ in result]
        self.assertNotIn("Encyclopedia", terms)
        self.assertNotIn("DamageGlossary", terms)
        self.assertIn("Star Port", terms)


class TestDurationHint(unittest.TestCase):
    def test_zero_batches(self):
        self.assertEqual(pf.estimate_duration_hint(0, 8), "nada a traduzir")

    def test_scales_with_workers(self):
        slow = pf.estimate_duration_hint(800, 1)
        fast = pf.estimate_duration_hint(800, 8)
        self.assertIn("h", slow)
        self.assertIn("min", fast)


class TestProgressParser(unittest.TestCase):
    def test_tqdm_line(self):
        line = ("Traduzindo:  45%|████▍     | 123/273 "
                "[00:12<00:30,  4.10item/s]")
        parsed = pf.parse_engine_line(line)
        self.assertEqual(parsed["kind"], "progress")
        self.assertEqual(parsed["done"], 123)
        self.assertEqual(parsed["total"], 273)
        self.assertEqual(parsed["eta"], "00:30")

    def test_plan_line(self):
        line = ("12:00:00 [INFO] Tradutor: Pendentes: 52100 | Exact EN: "
                "18000 | Inline locked: 312 | Já feitos: 0 | Pulados: 340")
        parsed = pf.parse_engine_line(line)
        self.assertEqual(parsed["kind"], "plan")
        self.assertEqual(parsed["pending"], 52100)
        self.assertEqual(parsed["exact"], 18000)
        self.assertEqual(parsed["inline"], 312)
        self.assertEqual(parsed["skipped"], 340)

    def test_final_line(self):
        line = ("12:30:00 [INFO] Tradutor: [OK] Concluído: 52100 "
                "traduzidos | 12 falhas | 18000 exact EN | 312 inline locked")
        parsed = pf.parse_engine_line(line)
        self.assertEqual(parsed["kind"], "final")
        self.assertEqual(parsed["success"], 52100)
        self.assertEqual(parsed["failed"], 12)
        self.assertEqual(parsed["exact"], 18000)

    def test_unrelated_lines_return_none(self):
        for line in ("", "random log noise", "Glossário: 2694 termos.",
                     "Config: model=x | mode=preserve"):
            self.assertIsNone(pf.parse_engine_line(line))


class TestSummarizeOutput(TempDirCase):
    def test_counts_by_flags(self):
        out = self.tmp / "out.json"
        data = {"strings": {
            "a": {"Offset": 0, "Text": "traduzida"},
            "b": {"Offset": 1, "Text": "outra traduzida"},
            "c": {"Offset": 2, "Text": "Plasma Gun", "_preserved": True},
            "d": {"Offset": 3, "Text": "placeholder",
                  "_skipped": "placeholder"},
            "e": {"Offset": 4, "Text": "falhou", "_failed": True},
        }}
        out.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        summary = pf.summarize_output(out)
        self.assertEqual(summary, {"translated": 2, "skipped_free": 2,
                                   "failed": 1})


class TestCredentials(TempDirCase):
    def test_env_key_resolution(self):
        import os
        old = os.environ.get("DEEPSEEK_API_KEY")
        os.environ["DEEPSEEK_API_KEY"] = "env-key-123"
        try:
            self.assertEqual(pf.env_api_key(), "env-key-123")
            key, source = pf.resolve_api_key("DeepSeek")
            self.assertEqual(key, "env-key-123")
            self.assertEqual(source, "variável de ambiente")
            # Campo digitado vence o ambiente.
            key, source = pf.resolve_api_key("DeepSeek", " typed ")
            self.assertEqual(key, "typed")
            self.assertEqual(source, "digitada agora")
        finally:
            if old is None:
                del os.environ["DEEPSEEK_API_KEY"]
            else:
                os.environ["DEEPSEEK_API_KEY"] = old

    def test_keyring_unavailable_graceful(self):
        # Neste ambiente keyring não está instalado — get/set degradam.
        if pf.keyring_available():
            self.skipTest("keyring instalado neste ambiente")
        self.assertEqual(pf.key_store_get("DeepSeek"), "")
        self.assertFalse(pf.key_store_set("DeepSeek", "secret"))
        # Sem chave em lugar nenhum → resolve vazio (nunca plaintext).
        import os
        saved = {v: os.environ.get(v) for v in pf.ENV_KEY_VARS}
        for v in pf.ENV_KEY_VARS:
            os.environ.pop(v, None)
        try:
            key, source = pf.resolve_api_key("DeepSeek")
            self.assertEqual((key, source), ("", ""))
        finally:
            for v, val in saved.items():
                if val is not None:
                    os.environ[v] = val

    def test_provider_key_name_mapping(self):
        self.assertEqual(pf.provider_key_name("DeepSeek"),
                         "api_key_deepseek")
        self.assertEqual(pf.provider_key_name("Zhipu GLM"), "api_key_zhipu")
        self.assertEqual(pf.provider_key_name("Kimi (Coding)"),
                         "api_key_kimi")
        self.assertEqual(pf.provider_key_name("outra coisa"),
                         "api_key_custom")

    def test_subprocess_env_injects_key_and_url(self):
        env = pf.subprocess_env("deepseek-v4-flash", "secret-key")
        self.assertEqual(env["DEEPSEEK_API_KEY"], "secret-key")
        self.assertEqual(env["OPENAI_API_KEY"], "secret-key")
        self.assertEqual(env["DEEPSEEK_BASE_URL"], "https://api.deepseek.com")

        env = pf.subprocess_env("glm-5.2", "k2")
        self.assertEqual(env["DEEPSEEK_BASE_URL"],
                         "https://open.bigmodel.cn/api/paas/v4")

        env = pf.subprocess_env("modelo-desconhecido", "k3")
        self.assertIn("DEEPSEEK_BASE_URL", env)


class TestResolveGlossaryPath(TempDirCase):
    def test_prefers_repo_root(self):
        repo = self.tmp / "repo"
        repo.mkdir()
        (repo / "glossary.json").write_text(
            json.dumps({"terms": []}), encoding="utf-8")
        project = wp.Project.create(self.tmp / "proj")
        found = pf.resolve_glossary_path(project, repo_root=repo)
        self.assertEqual(found, repo / "glossary.json")

    def test_missing_returns_none(self):
        project = wp.Project.create(self.tmp / "proj")
        self.assertIsNone(
            pf.resolve_glossary_path(project, repo_root=self.tmp / "nada"))


# ─────────────────────────────────────────────────────────────────────────────
# Teste de conexão (Issue 2) — servidor HTTP local, sem rede real
# ─────────────────────────────────────────────────────────────────────────────

import threading
from http.server import BaseHTTPRequestHandler, HTTPServer


class _ProbeHandler(BaseHTTPRequestHandler):
    """Modos: /models exige Bearer 'sk-ok'; /chat/completions sempre 200."""
    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/models":
            if self.headers.get("Authorization") == "Bearer sk-ok":
                self._send(200, {"data": []})
            else:
                self._send(401, {"error": {"message": "Invalid API key"}})
        elif self.path == "/sem-models":
            pass
        else:
            self._send(404, {"error": {"message": "not found"}})

    def do_POST(self):
        if self.path == "/chat/completions":
            if self.headers.get("Authorization") == "Bearer sk-ok":
                self._send(200, {"choices": []})
            else:
                self._send(401, {"error": {"message": "Invalid API key"}})
        else:
            self._send(404, {"error": {"message": "no route"}})

    def log_message(self, *a):
        pass


class TestConnectionProbe(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), _ProbeHandler)
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever,
                                      daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def test_models_ok_with_key(self):
        ok, msg = pf.test_connection(f"http://127.0.0.1:{self.port}",
                                     "sk-ok")
        self.assertTrue(ok)
        self.assertIn("HTTP 200", msg)

    def test_401_without_key_surfaces_server_message(self):
        ok, msg = pf.test_connection(f"http://127.0.0.1:{self.port}", "")
        self.assertFalse(ok)
        self.assertIn("401", msg)
        self.assertIn("Invalid API key", msg)  # mensagem exata do servidor

    def test_fallback_to_chat_when_models_missing(self):
        """Provedores sem /models (ex.: endpoint coding da Zhipu) ainda
        passam no probe de chat completions."""
        class _NoModels(_ProbeHandler):
            def do_GET(self):
                self._send(404, {"error": {"message": "no such route"}})

        server = HTTPServer(("127.0.0.1", 0), _NoModels)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            port = server.server_address[1]
            ok, msg = pf.test_connection(f"http://127.0.0.1:{port}",
                                         "sk-ok", model="glm-4.7-flash")
            self.assertTrue(ok)
            self.assertIn("chat completions", msg)
        finally:
            server.shutdown()

    def test_dead_port_reports_failure(self):
        ok, msg = pf.test_connection("http://127.0.0.1:1", "sk-ok",
                                     timeout=3.0)
        self.assertFalse(ok)
        self.assertTrue(msg.startswith("✖"))


# ─────────────────────────────────────────────────────────────────────────────
# Ciclo de vida da chave (Issue 3) — resolução idêntica nos 3 fluxos
# ─────────────────────────────────────────────────────────────────────────────

class _FakeKeyring:
    def __init__(self, fail_writes=False):
        self.store = {}
        self.fail_writes = fail_writes

    def get_password(self, service, name):
        return self.store.get((service, name))

    def set_password(self, service, name, value):
        if self.fail_writes:
            raise RuntimeError("backend quebrou")
        self.store[(service, name)] = value

    def delete_password(self, service, name):
        if (service, name) not in self.store:
            raise RuntimeError("not found")
        del self.store[(service, name)]


class TestKeyringDiagnostics(unittest.TestCase):
    def setUp(self):
        self._old_keyring = pf._keyring
        self._old_avail = pf._KEYRING_AVAILABLE

    def tearDown(self):
        pf._keyring = self._old_keyring
        pf._KEYRING_AVAILABLE = self._old_avail

    def test_set_ex_reports_missing_package(self):
        pf._keyring = None
        pf._KEYRING_AVAILABLE = False
        ok, detail = pf.key_store_set_ex("Zhipu GLM", "sk-x")
        self.assertFalse(ok)
        self.assertIn("keyring", detail)
        self.assertIn("pip install", detail)

    def test_set_ex_reports_backend_failure(self):
        pf._keyring = _FakeKeyring(fail_writes=True)
        pf._KEYRING_AVAILABLE = True
        ok, detail = pf.key_store_set_ex("Zhipu GLM", "sk-x")
        self.assertFalse(ok)
        self.assertIn("backend quebrou", detail)
        # wrapper bool continua False (nunca finge sucesso)
        self.assertFalse(pf.key_store_set("Zhipu GLM", "sk-x"))

    def test_set_ex_success_detail(self):
        pf._keyring = _FakeKeyring()
        pf._KEYRING_AVAILABLE = True
        ok, detail = pf.key_store_set_ex("Zhipu GLM", "sk-x")
        self.assertTrue(ok)
        self.assertIn("cofre", detail)


class TestCrossFlowKeyResolution(unittest.TestCase):
    """Wizard, audit retry e patch day resolvem a chave pelo MESMO caminho
    (provider_for_model → resolve_api_key: digitada → env → cofre, mesmos
    service/key names). Salvo num fluxo = lido nos outros."""

    def setUp(self):
        self._old_keyring = pf._keyring
        self._old_avail = pf._KEYRING_AVAILABLE
        pf._keyring = _FakeKeyring()
        pf._KEYRING_AVAILABLE = True
        import os
        self._saved_env = {v: os.environ.get(v) for v in pf.ENV_KEY_VARS}
        for v in pf.ENV_KEY_VARS:
            os.environ.pop(v, None)

    def tearDown(self):
        pf._keyring = self._old_keyring
        pf._KEYRING_AVAILABLE = self._old_avail
        import os
        for v, val in self._saved_env.items():
            if val is not None:
                os.environ[v] = val

    def test_saved_in_settings_read_by_all_flows(self):
        # Salvo pela aba Provedores das Configurações:
        self.assertTrue(pf.key_store_set("Zhipu GLM", "sk-zhipu"))
        # Os 3 fluxos resolvem exatamente assim (mesma sequência de chamadas
        # de w40k_translator.py: wizard _build_command/_start_run,
        # AuditDialog._retry_selected, PatchDayDialog._start_run):
        for model in ("glm-5.2", "glm-4.7-flash"):
            provider = pf.provider_for_model(model)
            self.assertEqual(provider, "Zhipu GLM")
            key, source = pf.resolve_api_key(provider, "")
            self.assertEqual(key, "sk-zhipu")
            self.assertEqual(source, "cofre do Windows")
        # Nomes de serviço/chave usados no cofre são os esperados:
        self.assertIn((pf.KEYRING_SERVICE, "api_key_zhipu"),
                      pf._keyring.store)

    def test_typed_beats_vault_everywhere(self):
        pf.key_store_set("DeepSeek", "sk-vault")
        provider = pf.provider_for_model("deepseek-v4-flash")
        key, source = pf.resolve_api_key(provider, "sk-typed")
        self.assertEqual((key, source), ("sk-typed", "digitada agora"))

    def test_delete_roundtrip(self):
        pf.key_store_set("Kimi (Coding)", "sk-kimi")
        self.assertEqual(pf.key_store_get("Kimi (Coding)"), "sk-kimi")
        self.assertTrue(pf.key_store_delete("Kimi (Coding)"))
        self.assertEqual(pf.key_store_get("Kimi (Coding)"), "")


if __name__ == "__main__":
    unittest.main()
