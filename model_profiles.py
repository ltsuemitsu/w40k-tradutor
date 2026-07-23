# -*- coding: utf-8 -*-
"""Model profiles for cost/throughput-aware translation.

Cache rule: keep SYSTEM + glossary prefix byte-stable across a run.
Only the user message (batch strings) should change → provider "cached input".
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

# Batch tiers: (short, medium, long, xlong) string counts
# workers: parallel API calls
# save_every: write full output JSON every N completed batches (1 = every batch)

PROFILES: Dict[str, Dict[str, Any]] = {
    # ── DeepSeek (recommended bulk) ──
    "deepseek-v4-flash": {
        "provider": "DeepSeek",
        "url": "https://api.deepseek.com",
        "label": "DeepSeek V4 Flash — bulk default (cheap + fast)",
        "batches": (100, 50, 15, 5),
        "workers": 8,
        "save_every": 8,
        "max_tokens_batch": 20000,
        "thinking": False,
        "role": "bulk",
    },
    "deepseek-v4-pro": {
        "provider": "DeepSeek",
        "url": "https://api.deepseek.com",
        "label": "DeepSeek V4 Pro — quality / hard rows",
        "batches": (60, 35, 12, 4),
        "workers": 4,
        "save_every": 6,
        "max_tokens_batch": 16000,
        "thinking": False,
        "role": "quality",
    },
    "deepseek-chat": {  # legacy alias → flash non-thinking
        "provider": "DeepSeek",
        "url": "https://api.deepseek.com",
        "label": "deepseek-chat (legacy → flash non-thinking)",
        "batches": (100, 50, 15, 5),
        "workers": 8,
        "save_every": 8,
        "max_tokens_batch": 20000,
        "alias_of": "deepseek-v4-flash",
        "role": "bulk",
    },
    "deepseek-reasoner": {
        "provider": "DeepSeek",
        "url": "https://api.deepseek.com",
        "label": "deepseek-reasoner (legacy → flash thinking)",
        "batches": (40, 25, 10, 3),
        "workers": 3,
        "save_every": 5,
        "max_tokens_batch": 12000,
        "thinking": True,
        "role": "quality",
    },
    # ── Zhipu GLM ──
    "glm-5.2": {
        "provider": "Zhipu GLM",
        "url": "https://open.bigmodel.cn/api/paas/v4",
        "label": "GLM-5.2 — premium voice (expensive output)",
        "batches": (70, 40, 10, 4),
        "workers": 3,
        "save_every": 5,
        "max_tokens_batch": 14000,
        "role": "quality",
    },
    "glm-5.1": {
        "provider": "Zhipu GLM",
        "url": "https://open.bigmodel.cn/api/paas/v4",
        "label": "GLM-5.1",
        "batches": (70, 40, 10, 4),
        "workers": 3,
        "save_every": 5,
        "max_tokens_batch": 14000,
        "role": "quality",
    },
    "glm-5": {
        "provider": "Zhipu GLM",
        "url": "https://open.bigmodel.cn/api/paas/v4",
        "label": "GLM-5",
        "batches": (80, 45, 12, 4),
        "workers": 3,
        "save_every": 6,
        "max_tokens_batch": 15000,
        "role": "quality",
    },
    "glm-5-turbo": {
        "provider": "Zhipu GLM",
        "url": "https://open.bigmodel.cn/api/paas/v4",
        "label": "GLM-5-Turbo",
        "batches": (80, 45, 12, 4),
        "workers": 4,
        "save_every": 6,
        "max_tokens_batch": 15000,
        "role": "bulk",
    },
    "glm-4.7": {
        "provider": "Zhipu GLM",
        "url": "https://open.bigmodel.cn/api/paas/v4",
        "label": "GLM-4.7",
        "batches": (90, 50, 14, 5),
        "workers": 4,
        "save_every": 8,
        "max_tokens_batch": 16000,
        "role": "bulk",
    },
    "glm-4.7-flash": {
        "provider": "Zhipu GLM",
        "url": "https://open.bigmodel.cn/api/paas/v4",
        "label": "GLM-4.7-Flash — free/cheap bulk on Zhipu",
        "batches": (100, 55, 16, 5),
        "workers": 6,
        "save_every": 10,
        "max_tokens_batch": 18000,
        "role": "bulk",
    },
    "glm-4.7-flashx": {
        "provider": "Zhipu GLM",
        "url": "https://open.bigmodel.cn/api/paas/v4",
        "label": "GLM-4.7-FlashX",
        "batches": (100, 55, 16, 5),
        "workers": 6,
        "save_every": 10,
        "max_tokens_batch": 18000,
        "role": "bulk",
    },
    "glm-4.5-flash": {
        "provider": "Zhipu GLM",
        "url": "https://open.bigmodel.cn/api/paas/v4",
        "label": "GLM-4.5-Flash — free bulk",
        "batches": (100, 55, 16, 5),
        "workers": 6,
        "save_every": 10,
        "max_tokens_batch": 18000,
        "role": "bulk",
    },
    "glm-4.5-air": {
        "provider": "Zhipu GLM",
        "url": "https://open.bigmodel.cn/api/paas/v4",
        "label": "GLM-4.5-Air — cheap",
        "batches": (90, 50, 14, 5),
        "workers": 5,
        "save_every": 8,
        "max_tokens_batch": 16000,
        "role": "bulk",
    },
    "glm-4-plus": {
        "provider": "Zhipu GLM",
        "url": "https://open.bigmodel.cn/api/paas/v4",
        "label": "glm-4-plus (legacy)",
        "batches": (50, 30, 12, 5),
        "workers": 3,
        "save_every": 5,
        "max_tokens_batch": 12500,
        "role": "quality",
    },
    "glm-4-flash": {
        "provider": "Zhipu GLM",
        "url": "https://open.bigmodel.cn/api/paas/v4",
        "label": "glm-4-flash (legacy)",
        "batches": (80, 45, 14, 5),
        "workers": 5,
        "save_every": 8,
        "max_tokens_batch": 15000,
        "role": "bulk",
    },
    # ── Kimi Coding ──
    "k3": {
        "provider": "Kimi (Coding)",
        "url": "https://api.kimi.com/coding/v1",
        "label": "Kimi K3 flagship (1M ctx)",
        "batches": (80, 45, 12, 4),
        "workers": 3,
        "save_every": 6,
        "max_tokens_batch": 16000,
        "role": "quality",
    },
    "kimi-for-coding": {
        "provider": "Kimi (Coding)",
        "url": "https://api.kimi.com/coding/v1",
        "label": "Kimi K2.7 Code (stable)",
        "batches": (70, 40, 12, 4),
        "workers": 3,
        "save_every": 6,
        "max_tokens_batch": 14000,
        "role": "quality",
    },
    "kimi-for-coding-highspeed": {
        "provider": "Kimi (Coding)",
        "url": "https://api.kimi.com/coding/v1",
        "label": "Kimi K2.7 Code HighSpeed (3× quota)",
        "batches": (90, 50, 14, 5),
        "workers": 4,
        "save_every": 8,
        "max_tokens_batch": 16000,
        "role": "bulk",
    },
}

# Fallback when model string is unknown
DEFAULT_PROFILE: Dict[str, Any] = {
    "provider": "Custom",
    "url": "",
    "label": "Generic OpenAI-compat",
    "batches": (50, 30, 12, 5),
    "workers": 3,
    "save_every": 5,
    "max_tokens_batch": 12500,
    "role": "bulk",
}

# Provider → default model for "Apply preset"
PROVIDER_DEFAULT_MODEL = {
    "DeepSeek": "deepseek-v4-flash",
    "Zhipu GLM": "glm-4.7-flash",
    "Kimi (Coding)": "kimi-for-coding",
    "Kimi (Moonshot)": "kimi-for-coding",  # legacy name
    "Custom (OpenAI-compat)": "deepseek-v4-flash",
}

PROVIDER_URLS = {
    "DeepSeek": "https://api.deepseek.com",
    "Zhipu GLM": "https://open.bigmodel.cn/api/paas/v4",
    "Kimi (Coding)": "https://api.kimi.com/coding/v1",
    "Kimi (Moonshot)": "https://api.kimi.com/coding/v1",
    "Custom (OpenAI-compat)": "https://api.openai.com/v1",
}


def normalize_model_id(model: str) -> str:
    m = (model or "").strip()
    return m


def resolve_profile(model: str) -> Tuple[str, Dict[str, Any]]:
    """Return (resolved_model_id, profile dict copy)."""
    mid = normalize_model_id(model)
    key = mid.lower()
    # exact
    for k, p in PROFILES.items():
        if k.lower() == key:
            out = dict(p)
            alias = out.pop("alias_of", None)
            if alias and alias in PROFILES:
                base = dict(PROFILES[alias])
                base.update({x: out[x] for x in out if x not in ("label",)})
                return alias, base
            return k, out
    # prefix / contains heuristics
    if "deepseek" in key and "pro" in key:
        return "deepseek-v4-pro", dict(PROFILES["deepseek-v4-pro"])
    if "deepseek" in key and ("flash" in key or "chat" in key):
        return "deepseek-v4-flash", dict(PROFILES["deepseek-v4-flash"])
    if "glm-5.2" in key or "glm5.2" in key:
        return "glm-5.2", dict(PROFILES["glm-5.2"])
    if "glm-4.7-flash" in key:
        return "glm-4.7-flash", dict(PROFILES["glm-4.7-flash"])
    if "flash" in key and "glm" in key:
        return "glm-4.5-flash", dict(PROFILES["glm-4.5-flash"])
    if key in ("k3",) or key.startswith("kimi-k3"):
        return "k3", dict(PROFILES["k3"])
    if "highspeed" in key:
        return "kimi-for-coding-highspeed", dict(PROFILES["kimi-for-coding-highspeed"])
    if "kimi" in key and "coding" in key:
        return "kimi-for-coding", dict(PROFILES["kimi-for-coding"])
    return mid, dict(DEFAULT_PROFILE)


def batch_tiers(model: str, optimized: bool = True) -> Tuple[int, int, int, int]:
    _, p = resolve_profile(model)
    b = p.get("batches") or DEFAULT_PROFILE["batches"]
    if not optimized:
        # conservative shrink
        return tuple(max(2, x // 2) for x in b)  # type: ignore
    return tuple(b)  # type: ignore


def recommended_workers(model: str) -> int:
    _, p = resolve_profile(model)
    return int(p.get("workers") or 3)


def save_every_batches(model: str) -> int:
    _, p = resolve_profile(model)
    return max(1, int(p.get("save_every") or 5))


def max_tokens_per_batch(model: str) -> int:
    _, p = resolve_profile(model)
    return int(p.get("max_tokens_batch") or 12500)


def models_for_provider(provider: str) -> List[str]:
    ids = []
    for mid, p in PROFILES.items():
        if p.get("provider") == provider or (
            provider.startswith("Kimi") and str(p.get("provider", "")).startswith("Kimi")
        ):
            ids.append(mid)
    return ids


def profile_summary(model: str) -> str:
    rid, p = resolve_profile(model)
    b = p.get("batches") or (50, 30, 12, 5)
    return (
        f"{p.get('label', rid)} | batches short/med/long/xlong={b[0]}/{b[1]}/{b[2]}/{b[3]} "
        f"| workers={p.get('workers')} | save_every={p.get('save_every')} | role={p.get('role')}"
    )
