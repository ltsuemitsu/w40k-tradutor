"""W40K Translator — Configurações do usuário (P6, sem Qt).

Camada de overrides DO USUÁRIO sobre os padrões de código de
`model_profiles.py` (que é somente-leitura). Persistência FORA do
repositório e dos projetos:

    %APPDATA%/W40KTranslator/user_providers.json
    %APPDATA%/W40KTranslator/user_profiles.json

(o diretório pode ser redirecionado pela variável de ambiente
W40K_CONFIG_DIR — usado por testes e smokes para nunca tocar o
%APPDATA% real.)

Formatos (JSON tolerante: arquivo ausente/malformado degrada para {}

  user_providers.json:
    {"providers": {"Zhipu GLM": {"base_url": "https://..."}},
     "custom_providers": {"Meu Provedor": {"base_url": "https://...",
                                           "kind": "openai"}}}

  user_profiles.json:
    {"overrides": {"glm-4.7-flash": {"workers": 6}},
     "profiles":  {"meu-modelo": {…perfil completo…}},
     "default_model": "deepseek-v4-flash"}

Precedência de resolução (sempre: usuário → código):
  - perfil de modelo: campo a campo, override do usuário sobre a linha
    de código; modelos adicionados pelo usuário vivem só dele.
  - base URL efetiva de um modelo:
      1) campo "url" do perfil quando o PRÓPRIO USUÁRIO o definiu
         (override ou modelo adicionado);
      2) override de base URL no nível do provedor;
      3) "url" embutido no perfil de código / PROVIDER_URLS.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:
    import model_profiles as _profiles
    _HAVE_PROFILES = True
except Exception:  # pragma: no cover - ambiente sem model_profiles
    _profiles = None
    _HAVE_PROFILES = False

CONFIG_DIR_ENV = "W40K_CONFIG_DIR"
APP_DIR_NAME = "W40KTranslator"
USER_PROVIDERS_FILE = "user_providers.json"
USER_PROFILES_FILE = "user_profiles.json"

DEFAULT_MODEL_FALLBACK = "deepseek-v4-flash"

# Campos editáveis de um perfil (espelha model_profiles.PROFILES).
PROFILE_FIELDS = (
    "provider", "url", "label", "batches", "workers",
    "save_every", "max_tokens_batch", "thinking", "role",
)

_FALLBACK_PROFILE: Dict[str, Any] = {
    "provider": "Custom",
    "url": "",
    "label": "Generic OpenAI-compat",
    "batches": (50, 30, 12, 5),
    "workers": 3,
    "save_every": 5,
    "max_tokens_batch": 12500,
    "role": "bulk",
}


# ─────────────────────────────────────────────────────────────────────────────
# Localização e IO dos arquivos de configuração
# ─────────────────────────────────────────────────────────────────────────────

def config_dir() -> Path:
    override = os.environ.get(CONFIG_DIR_ENV)
    if override:
        return Path(override)
    appdata = os.environ.get("APPDATA")
    if appdata:
        return Path(appdata) / APP_DIR_NAME
    return Path.home() / ".w40k_translator"  # pragma: no cover - não-Windows


def user_providers_path() -> Path:
    return config_dir() / USER_PROVIDERS_FILE


def user_profiles_path() -> Path:
    return config_dir() / USER_PROFILES_FILE


def _read_json(path: Path) -> Dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_json(path: Path, data: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    tmp.replace(path)


def load_user_providers() -> Dict[str, Any]:
    return _read_json(user_providers_path())


def save_user_providers(data: Dict[str, Any]) -> None:
    _write_json(user_providers_path(), data)


def load_user_profiles() -> Dict[str, Any]:
    return _read_json(user_profiles_path())


def save_user_profiles(data: Dict[str, Any]) -> None:
    _write_json(user_profiles_path(), data)


# ─────────────────────────────────────────────────────────────────────────────
# Provedores
# ─────────────────────────────────────────────────────────────────────────────

def code_providers() -> Dict[str, str]:
    if _HAVE_PROFILES:
        return dict(_profiles.PROVIDER_URLS)
    return {}


def provider_overrides() -> Dict[str, str]:
    """{provedor: base_url} — overrides do usuário sobre provedores de código."""
    raw = load_user_providers().get("providers") or {}
    out: Dict[str, str] = {}
    if isinstance(raw, dict):
        for name, info in raw.items():
            if isinstance(info, dict):
                url = str(info.get("base_url") or "").strip()
                if url:
                    out[str(name)] = url
    return out


def custom_providers() -> Dict[str, Dict[str, str]]:
    """{nome: {"base_url": ..., "kind": ...}} — provedores criados pelo usuário."""
    raw = load_user_providers().get("custom_providers") or {}
    out: Dict[str, Dict[str, str]] = {}
    if isinstance(raw, dict):
        for name, info in raw.items():
            if isinstance(info, dict):
                url = str(info.get("base_url") or "").strip()
                if url:
                    out[str(name)] = {
                        "base_url": url,
                        "kind": str(info.get("kind") or "openai"),
                    }
    return out


def effective_providers() -> Dict[str, str]:
    """{provedor: base_url efetiva} = código + custom + overrides."""
    eff = code_providers()
    for name, info in custom_providers().items():
        eff[name] = info["base_url"]
    eff.update(provider_overrides())
    return eff


def provider_base_url(provider: str) -> str:
    return effective_providers().get(provider, "")


def set_provider_base_url(provider: str, base_url: str) -> None:
    """Grava (ou limpa, se vazio) o override de base URL do provedor."""
    data = load_user_providers()
    provs = data.setdefault("providers", {})
    if not isinstance(provs, dict):
        provs = data["providers"] = {}
    url = (base_url or "").strip()
    if url:
        provs[provider] = {"base_url": url}
    else:
        provs.pop(provider, None)
    save_user_providers(data)


def add_custom_provider(name: str, base_url: str, kind: str = "openai") -> None:
    name = (name or "").strip()
    url = (base_url or "").strip()
    if not name or not url:
        raise ValueError("nome e base_url são obrigatórios")
    data = load_user_providers()
    customs = data.setdefault("custom_providers", {})
    if not isinstance(customs, dict):
        customs = data["custom_providers"] = {}
    customs[name] = {"base_url": url, "kind": (kind or "openai").strip()}
    save_user_providers(data)


def remove_custom_provider(name: str) -> None:
    data = load_user_providers()
    customs = data.get("custom_providers")
    if isinstance(customs, dict):
        customs.pop(name, None)
    save_user_providers(data)


# ─────────────────────────────────────────────────────────────────────────────
# Perfis de modelo
# ─────────────────────────────────────────────────────────────────────────────

def _normalize_profile(p: Dict[str, Any]) -> Dict[str, Any]:
    """Coage tipos vindos de JSON (batches vira tupla, ints de verdade)."""
    out = dict(p)
    if "batches" in out:
        b = out["batches"]
        try:
            out["batches"] = tuple(int(x) for x in b)
        except Exception:
            out.pop("batches", None)
    for key in ("workers", "save_every", "max_tokens_batch"):
        if key in out:
            try:
                out[key] = int(out[key])
            except (TypeError, ValueError):
                out.pop(key, None)
    return out


def code_profiles() -> Dict[str, Dict[str, Any]]:
    if _HAVE_PROFILES:
        return {mid: dict(p) for mid, p in _profiles.PROFILES.items()}
    return {}


def user_profile_overrides() -> Dict[str, Dict[str, Any]]:
    """{modelo: {campo: valor}} — overrides campo a campo sobre linhas de código."""
    raw = load_user_profiles().get("overrides") or {}
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw, dict):
        for mid, fields in raw.items():
            if isinstance(fields, dict) and fields:
                out[str(mid)] = dict(fields)
    return out


def user_added_profiles() -> Dict[str, Dict[str, Any]]:
    """{modelo: perfil completo} — modelos criados pelo usuário."""
    raw = load_user_profiles().get("profiles") or {}
    out: Dict[str, Dict[str, Any]] = {}
    if isinstance(raw, dict):
        for mid, prof in raw.items():
            if isinstance(prof, dict):
                out[str(mid)] = _normalize_profile(prof)
    return out


def effective_profiles() -> Dict[str, Dict[str, Any]]:
    """Perfis efetivos = código → overrides campo a campo → modelos do usuário."""
    eff = code_profiles()
    for mid, fields in user_profile_overrides().items():
        merged = dict(eff.get(mid) or _FALLBACK_PROFILE)
        merged.update(fields)
        eff[mid] = _normalize_profile(merged)
    for mid, prof in user_added_profiles().items():
        merged = dict(eff.get(mid) or {})
        merged.update(prof)
        eff[mid] = _normalize_profile(merged)
    return eff


def is_code_profile(model: str) -> bool:
    return (model or "") in code_profiles()


def is_user_profile(model: str) -> bool:
    return (model or "") in user_added_profiles()


def set_profile_override(model: str, fields: Dict[str, Any]) -> None:
    """Mescla overrides campo a campo numa linha (de código ou do usuário).
    `fields` vazio remove o override."""
    model = (model or "").strip()
    if not model:
        raise ValueError("modelo obrigatório")
    data = load_user_profiles()
    ovr = data.setdefault("overrides", {})
    if not isinstance(ovr, dict):
        ovr = data["overrides"] = {}
    clean = {k: v for k, v in (fields or {}).items() if k in PROFILE_FIELDS}
    if clean:
        existing = ovr.get(model)
        merged = dict(existing) if isinstance(existing, dict) else {}
        merged.update(clean)
        ovr[model] = merged
    else:
        ovr.pop(model, None)
    save_user_profiles(data)


def reset_profile_overrides(model: str) -> None:
    """Volta a linha (de código) aos padrões — remove todos os overrides."""
    data = load_user_profiles()
    ovr = data.get("overrides")
    if isinstance(ovr, dict):
        ovr.pop(model, None)
    save_user_profiles(data)


def add_user_profile(model: str, profile: Dict[str, Any]) -> None:
    model = (model or "").strip()
    if not model:
        raise ValueError("modelo obrigatório")
    if not str(profile.get("provider") or "").strip():
        raise ValueError("provider obrigatório")
    data = load_user_profiles()
    profs = data.setdefault("profiles", {})
    if not isinstance(profs, dict):
        profs = data["profiles"] = {}
    profs[model] = _normalize_profile(
        {k: v for k, v in profile.items() if k in PROFILE_FIELDS})
    save_user_profiles(data)


def remove_user_profile(model: str) -> None:
    """Remove modelo adicionado pelo usuário (e overrides residuais dele).
    Linhas de código não são removíveis — só resetáveis."""
    data = load_user_profiles()
    profs = data.get("profiles")
    if isinstance(profs, dict):
        profs.pop(model, None)
    ovr = data.get("overrides")
    if isinstance(ovr, dict):
        ovr.pop(model, None)
    save_user_profiles(data)


def default_model() -> str:
    """Modelo padrão dos pickers: escolha do usuário → fallback de código."""
    mid = str(load_user_profiles().get("default_model") or "").strip()
    if mid:
        return mid
    profiles = effective_profiles()
    if DEFAULT_MODEL_FALLBACK in profiles:
        return DEFAULT_MODEL_FALLBACK
    return next(iter(profiles), "")


def set_default_model(model: str) -> None:
    data = load_user_profiles()
    mid = (model or "").strip()
    if mid:
        data["default_model"] = mid
    else:
        data.pop("default_model", None)
    save_user_profiles(data)


def list_effective_models() -> List[Tuple[str, str, str]]:
    """[(model_id, label, provider)] efetivos, para os pickers da GUI."""
    return [
        (mid, str(p.get("label") or mid), str(p.get("provider") or ""))
        for mid, p in effective_profiles().items()
    ]


def probe_model_for_provider(provider: str) -> str:
    """Modelo configurado mais barato do provedor, para o teste de conexão
    (probe de chat completions com 1 token)."""
    if _HAVE_PROFILES:
        default = _profiles.PROVIDER_DEFAULT_MODEL.get(provider)
        if default:
            return default
        ids = _profiles.models_for_provider(provider)
        if ids:
            return ids[0]
    # Provedor custom: usa o primeiro modelo efetivo desse provedor, senão
    # o default global.
    for mid, p in effective_profiles().items():
        if str(p.get("provider") or "") == provider:
            return mid
    return default_model()


# ─────────────────────────────────────────────────────────────────────────────
# Resolução efetiva (espelha model_profiles.resolve_profile + URL efetiva)
# ─────────────────────────────────────────────────────────────────────────────

def _user_url_for(mid: str, added: Dict[str, Dict[str, Any]],
                  overrides: Dict[str, Dict[str, Any]]) -> str:
    """URL definida explicitamente pelo usuário para ESTE modelo (se houver)."""
    url = ""
    if mid in added and "url" in added[mid]:
        url = str(added[mid]["url"] or "").strip()
    if mid in overrides and "url" in overrides[mid]:
        url = str(overrides[mid]["url"] or "").strip()
    return url


def _apply_effective_url(mid: str, prof: Dict[str, Any],
                         prov_eff: Dict[str, str],
                         added: Dict[str, Dict[str, Any]],
                         overrides: Dict[str, Dict[str, Any]]
                         ) -> Dict[str, Any]:
    """Precedência da base URL: url do usuário no modelo → override do
    provedor → url embutida no perfil → PROVIDER_URLS efetivo."""
    out = dict(prof)
    user_url = _user_url_for(mid, added, overrides)
    if user_url:
        out["url"] = user_url
        return out
    provider = str(out.get("provider") or "")
    if provider in prov_eff and prov_eff[provider] != code_providers().get(
            provider, ""):
        out["url"] = prov_eff[provider]
        return out
    if not str(out.get("url") or "").strip():
        out["url"] = prov_eff.get(provider, "")
    return out


def resolve_effective_profile(model: str) -> Tuple[str, Dict[str, Any]]:
    """(resolved_id, perfil efetivo) — mesma semântica de
    model_profiles.resolve_profile, mas sobre os perfis efetivos e já com
    a base URL efetiva injetada."""
    profiles = effective_profiles()
    prov_eff = effective_providers()
    added = user_added_profiles()
    overrides = user_profile_overrides()

    mid = (model or "").strip()
    key = mid.lower()
    for k, p in profiles.items():
        if k.lower() == key:
            out = dict(p)
            alias = out.pop("alias_of", None)
            if alias and alias in profiles:
                base = dict(profiles[alias])
                base.update({x: out[x] for x in out if x != "label"})
                return alias, _apply_effective_url(
                    alias, base, prov_eff, added, overrides)
            return k, _apply_effective_url(k, out, prov_eff, added, overrides)

    # Heurísticas de prefixo/alias do código: resolve o id e re-mescla com
    # a linha efetiva correspondente (que já inclui overrides do usuário).
    if _HAVE_PROFILES:
        rid, prof = _profiles.resolve_profile(mid)
        if rid in profiles:
            merged = dict(prof)
            merged.update(profiles[rid])
            prof = merged
        return rid, _apply_effective_url(rid, prof, prov_eff, added, overrides)

    return mid, _apply_effective_url(mid, dict(_FALLBACK_PROFILE),
                                     prov_eff, added, overrides)
