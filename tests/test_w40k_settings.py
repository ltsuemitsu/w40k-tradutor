"""Testes de w40k_settings — overrides de provedores/perfis (stdlib only).

Cada teste isola a pasta de configuração via W40K_CONFIG_DIR num
TemporaryDirectory — nunca toca o %APPDATA% real nem o keyring.
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

try:
    import _isolate  # noqa: F401 — isola W40K_CONFIG_DIR (flat discovery)
except ImportError:
    pass  # modo pacote: tests/__init__.py já isolou

import model_profiles as mp
import w40k_preflight as pf
import w40k_settings as st

ZHIPU_CODE_URL = mp.PROVIDER_URLS["Zhipu GLM"]


class SettingsCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._old_env = os.environ.get("W40K_CONFIG_DIR")
        os.environ["W40K_CONFIG_DIR"] = self.tmp.name

    def tearDown(self):
        if self._old_env is None:
            os.environ.pop("W40K_CONFIG_DIR", None)
        else:
            os.environ["W40K_CONFIG_DIR"] = self._old_env

    @property
    def cfg(self) -> Path:
        return Path(self.tmp.name)


class TestConfigDir(SettingsCase):
    def test_env_override_wins(self):
        self.assertEqual(st.config_dir(), Path(self.tmp.name))
        self.assertEqual(st.user_providers_path(),
                         self.cfg / "user_providers.json")
        self.assertEqual(st.user_profiles_path(),
                         self.cfg / "user_profiles.json")


class TestProviders(SettingsCase):
    def test_defaults_are_code_providers(self):
        eff = st.effective_providers()
        self.assertEqual(eff["Zhipu GLM"], ZHIPU_CODE_URL)
        self.assertEqual(eff["DeepSeek"], "https://api.deepseek.com")

    def test_provider_url_override_and_reset(self):
        st.set_provider_base_url("Zhipu GLM", "https://glm.coding.example/v1")
        self.assertEqual(st.provider_base_url("Zhipu GLM"),
                         "https://glm.coding.example/v1")
        # Override no nível do provedor vence a url embutida no perfil.
        _rid, prof = st.resolve_effective_profile("glm-5.2")
        self.assertEqual(prof["url"], "https://glm.coding.example/v1")
        # E chega ao env do subprocess.
        env = pf.subprocess_env("glm-5.2", "k")
        self.assertEqual(env["DEEPSEEK_BASE_URL"],
                         "https://glm.coding.example/v1")
        self.assertEqual(env["ZHIPU_API_KEY"], "k")
        # Reset (string vazia) volta ao padrão de código.
        st.set_provider_base_url("Zhipu GLM", "")
        self.assertEqual(st.provider_base_url("Zhipu GLM"), ZHIPU_CODE_URL)
        self.assertNotIn("Zhipu GLM", st.provider_overrides())

    def test_custom_provider_add_and_remove(self):
        st.add_custom_provider("Meu Proxy", "https://proxy.example/v1")
        self.assertEqual(st.provider_base_url("Meu Proxy"),
                         "https://proxy.example/v1")
        customs = st.custom_providers()
        self.assertEqual(customs["Meu Proxy"]["kind"], "openai")
        st.remove_custom_provider("Meu Proxy")
        self.assertNotIn("Meu Proxy", st.effective_providers())

    def test_custom_provider_requires_name_and_url(self):
        with self.assertRaises(ValueError):
            st.add_custom_provider("", "https://x.example")
        with self.assertRaises(ValueError):
            st.add_custom_provider("X", "")


class TestProfiles(SettingsCase):
    def test_per_field_override_and_reset(self):
        code_workers = mp.PROFILES["glm-4.7-flash"]["workers"]
        st.set_profile_override("glm-4.7-flash", {"workers": 6})
        _rid, prof = st.resolve_effective_profile("glm-4.7-flash")
        self.assertEqual(prof["workers"], 6)
        # Demais campos continuam os de código.
        self.assertEqual(prof["label"],
                         mp.PROFILES["glm-4.7-flash"]["label"])
        self.assertEqual(tuple(prof["batches"]),
                         tuple(mp.PROFILES["glm-4.7-flash"]["batches"]))
        st.reset_profile_overrides("glm-4.7-flash")
        _rid, prof = st.resolve_effective_profile("glm-4.7-flash")
        self.assertEqual(prof["workers"], code_workers)

    def test_override_ignores_unknown_fields(self):
        st.set_profile_override("glm-4.7-flash",
                                {"workers": 7, "campo_inventado": 1})
        ovr = st.user_profile_overrides()["glm-4.7-flash"]
        self.assertIn("workers", ovr)
        self.assertNotIn("campo_inventado", ovr)

    def test_user_profile_add_edit_remove(self):
        profile = {
            "provider": "Zhipu GLM",
            "label": "GLM Coding",
            "batches": [40, 20, 8, 4],   # JSON dá lista; vira tupla
            "workers": 4,
            "save_every": 5,
            "max_tokens_batch": 9000,
            "role": "quality",
        }
        st.add_user_profile("glm-coding", profile)
        self.assertTrue(st.is_user_profile("glm-coding"))
        rid, prof = st.resolve_effective_profile("glm-coding")
        self.assertEqual(rid, "glm-coding")
        self.assertEqual(prof["workers"], 4)
        self.assertEqual(prof["batches"], (40, 20, 8, 4))
        # Sem "url" no perfil → herda a base URL efetiva do provedor.
        self.assertEqual(prof["url"], ZHIPU_CODE_URL)
        # Aparece nos pickers via preflight.
        ids = [m[0] for m in pf.list_models()]
        self.assertIn("glm-coding", ids)
        self.assertEqual(pf.provider_for_model("glm-coding"), "Zhipu GLM")
        # Edição = regravar o perfil completo.
        profile["workers"] = 9
        st.add_user_profile("glm-coding", profile)
        _rid, prof = st.resolve_effective_profile("glm-coding")
        self.assertEqual(prof["workers"], 9)
        # Remoção some do picker.
        st.remove_user_profile("glm-coding")
        self.assertFalse(st.is_user_profile("glm-coding"))
        ids = [m[0] for m in pf.list_models()]
        self.assertNotIn("glm-coding", ids)

    def test_add_user_profile_requires_provider(self):
        with self.assertRaises(ValueError):
            st.add_user_profile("x", {"label": "sem provider"})

    def test_user_model_url_beats_provider_override(self):
        st.set_provider_base_url("Zhipu GLM", "https://glm.override/v1")
        st.add_user_profile("glm-coding", {
            "provider": "Zhipu GLM",
            "url": "https://glm.do-usuario/v1",
            "workers": 3, "save_every": 5,
            "max_tokens_batch": 1000, "batches": [10, 5, 3, 2],
        })
        _rid, prof = st.resolve_effective_profile("glm-coding")
        self.assertEqual(prof["url"], "https://glm.do-usuario/v1")

    def test_model_without_url_inherits_provider_override(self):
        st.set_provider_base_url("Zhipu GLM", "https://glm.override/v1")
        st.add_user_profile("glm-coding", {
            "provider": "Zhipu GLM",
            "workers": 3, "save_every": 5,
            "max_tokens_batch": 1000, "batches": [10, 5, 3, 2],
        })
        _rid, prof = st.resolve_effective_profile("glm-coding")
        self.assertEqual(prof["url"], "https://glm.override/v1")

    def test_alias_resolution_uses_effective(self):
        # Override na linha do alias aplica normalmente.
        st.set_profile_override("deepseek-chat", {"workers": 11})
        rid, prof = st.resolve_effective_profile("deepseek-chat")
        self.assertEqual(rid, "deepseek-v4-flash")
        self.assertEqual(prof["workers"], 11)
        # Override SÓ no alvo não vaza pelo alias — a linha do alias tem
        # campos próprios que vencem (semântica de resolve_profile do
        # código, preservada de propósito).
        st.reset_profile_overrides("deepseek-chat")
        st.set_profile_override("deepseek-v4-flash", {"workers": 5})
        _rid, prof = st.resolve_effective_profile("deepseek-chat")
        self.assertEqual(prof["workers"], 8)
        # …mas resolve direto no alvo pega o override.
        _rid, prof = st.resolve_effective_profile("deepseek-v4-flash")
        self.assertEqual(prof["workers"], 5)

    def test_unknown_model_heuristic_still_works(self):
        rid, prof = st.resolve_effective_profile("glm-5.2-turbo-x")
        self.assertEqual(rid, "glm-5.2")
        rid, prof = st.resolve_effective_profile("modelo-nada-a-ver")
        self.assertEqual(rid, "modelo-nada-a-ver")
        self.assertEqual(prof["provider"], "Custom")


class TestDefaultModel(SettingsCase):
    def test_fallback_is_code_default(self):
        self.assertEqual(st.default_model(), "deepseek-v4-flash")

    def test_set_and_clear(self):
        st.set_default_model("glm-5.2")
        self.assertEqual(st.default_model(), "glm-5.2")
        st.set_default_model("")
        self.assertEqual(st.default_model(), "deepseek-v4-flash")


class TestPersistence(SettingsCase):
    def test_roundtrip_on_disk(self):
        st.set_provider_base_url("Zhipu GLM", "https://glm.override/v1")
        st.add_custom_provider("Proxy", "https://proxy.example/v1")
        st.set_profile_override("glm-4.7-flash", {"workers": 6})
        st.set_default_model("glm-5.2")
        # Relê direto do disco (sem cache em memória).
        prov = json.loads((self.cfg / "user_providers.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual(prov["providers"]["Zhipu GLM"]["base_url"],
                         "https://glm.override/v1")
        self.assertEqual(prov["custom_providers"]["Proxy"]["base_url"],
                         "https://proxy.example/v1")
        prof = json.loads((self.cfg / "user_profiles.json")
                          .read_text(encoding="utf-8"))
        self.assertEqual(prof["overrides"]["glm-4.7-flash"]["workers"], 6)
        self.assertEqual(prof["default_model"], "glm-5.2")

    def test_malformed_json_degrades_to_code_defaults(self):
        (self.cfg / "user_providers.json").write_text(
            "{não é json", encoding="utf-8")
        (self.cfg / "user_profiles.json").write_text(
            "[1, 2, 3]", encoding="utf-8")
        self.assertEqual(st.provider_base_url("Zhipu GLM"), ZHIPU_CODE_URL)
        self.assertEqual(st.default_model(), "deepseek-v4-flash")
        _rid, prof = st.resolve_effective_profile("glm-5.2")
        self.assertEqual(prof["url"], ZHIPU_CODE_URL)
        # E ainda dá para gravar por cima do lixo.
        st.set_provider_base_url("Zhipu GLM", "https://novo.example/v1")
        self.assertEqual(st.provider_base_url("Zhipu GLM"),
                         "https://novo.example/v1")


if __name__ == "__main__":
    unittest.main()
