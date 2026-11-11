"""LLM endpoint SSoT for lg_mangaka graphs.

Per ADR-2606271100 (Murakumo fleet + LiteLLM gateway — the org-wide LLM
inference SSoT since 2026-06-27), every text LLM call goes through the
Mac-mini fleet LiteLLM OpenAI-compatible gateway. The previous primary — the
Vultr A16-16Q ``litellm`` pool (ADR-2605211000, ``keiei-litellm`` in-cluster
service) — was decommissioned along with the rest of the Vultr VKE fleet
(ADR-2606120930, VKE deleted 2026-06-24); its old in-cluster DNS name is no
longer reachable and MUST NOT be used as a default.

This module is the single place that resolves the chat-completions base URL,
model id, bearer token and timeout, so no individual graph hardcodes a
provider endpoint or model name (AGENTS.md guardrail ``llm-model-ssot``). The
base-URL resolution mirrors ``resolveLlmEndpoint()`` in
``orgs/gftdcojp/ai-gftd-magatama-host-sdk/src/llm-model-registry.ts``
(the TypeScript SSoT for the same fleet), so a pod env that drives the rest
of the platform drives mangaka too:

  base URL : MURAKUMO_LLM_URL / GFTD_LLM_URL / LOCAL_LLM_ENDPOINT / VLLM_URL
  model    : LOCAL_LLM_MODEL / VLLM_MODEL
  bearer   : LOCAL_LLM_API_KEY / GFTD_LLM_API_KEY / VLLM_API_KEY
  timeout  : VLLM_TIMEOUT_SEC

The default base URL is the canonical Murakumo OpenAI-compatible API
(``https://api.murakumo.cloud/v1``), used when neither
``MURAKUMO_LLM_URL`` nor ``GFTD_LLM_URL`` is set.
"""

from __future__ import annotations

import os

# Canonical Murakumo OpenAI-compatible API. Superseded defaults (do not
# reintroduce): the retired gftd.ai LiteLLM gateways and the
# retired Vultr `keiei-litellm.keiei-llm.svc.cluster.local:4000` service,
# gone since the VKE winddown (ADR-2606120930).
_DEFAULT_BASE_URL = "https://api.murakumo.cloud/v1"
_DEFAULT_MODEL = "murakumo-main"
_DEFAULT_TIMEOUT = 60.0


def _first_env(*names: str) -> str:
    for n in names:
        v = os.environ.get(n)
        if v and v.strip():
            return v.strip()
    return ""


def _normalize_base(url: str) -> str:
    """Return an OpenAI-style base URL ending in ``/v1`` (no trailing slash).

    Tolerates a configured full chat-completions URL (strips the
    ``/chat/completions`` suffix) so either env style works.
    """
    u = url.rstrip("/")
    if u.endswith("/chat/completions"):
        u = u[: -len("/chat/completions")]
    return u.rstrip("/")


def base_url() -> str:
    """OpenAI-compatible base URL (``…/v1``).

    Resolution order matches ``resolveLlmEndpoint()`` (light tier) in
    ``llm-model-registry.ts``: ``MURAKUMO_LLM_URL`` -> ``GFTD_LLM_URL`` ->
    default. ``LOCAL_LLM_ENDPOINT`` / ``VLLM_URL`` remain as legacy
    lower-priority overrides for existing local-dev configs.
    """
    return _normalize_base(
        _first_env(
            "MURAKUMO_LLM_URL",
            "GFTD_LLM_URL",
            "LLM_CHAT_COMPLETIONS_URL",
            "LOCAL_LLM_ENDPOINT",
            "VLLM_URL",
        )
        or _DEFAULT_BASE_URL
    )


def chat_completions_url() -> str:
    """Fully-qualified ``…/v1/chat/completions`` endpoint."""
    return f"{base_url()}/chat/completions"


def default_model() -> str:
    return _first_env("LOCAL_LLM_MODEL", "VLLM_MODEL") or _DEFAULT_MODEL


def api_key() -> str:
    """Bearer token (empty string when unauthenticated, e.g. local dev)."""
    return _first_env("LOCAL_LLM_API_KEY", "GFTD_LLM_API_KEY", "VLLM_API_KEY")


def timeout_sec() -> float:
    raw = os.environ.get("VLLM_TIMEOUT_SEC")
    if raw:
        try:
            return float(raw)
        except ValueError:
            pass
    return _DEFAULT_TIMEOUT


def auth_headers() -> dict[str, str]:
    """Standard headers for a chat/completions POST, including bearer if set."""
    headers = {"Content-Type": "application/json"}
    key = api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


# ── Ollama / vision-QA backend ────────────────────────────────────────────
# The v10/v11 scoring + pose/scene modules grade rendered PNG panels with a
# vision-capable model served by a local Ollama daemon (OpenAI-compatible at
# `/v1/chat/completions`, native at `/api/generate`). Previously each module
# re-declared its own `OLLAMA` / `MODEL` constants — eight call sites with
# three divergent defaults (localhost vs 192.168.1.23, gemma3:4b vs gemma4,
# one fully hardcoded). Centralized here so the host and the vision model can
# be bumped in ONE place. The intended upgrade is `gemma3:4b` →
# `gemma-4-E4B-it` once the local Ollama gains gemma4 arch support (see the
# narrative_qa.py header note); flip `_DEFAULT_VISION_MODEL` then.

_DEFAULT_OLLAMA_URL = "http://localhost:11434"
_DEFAULT_VISION_MODEL = "gemma3:4b"


def ollama_url() -> str:
    """Base URL of the vision-QA Ollama daemon (no trailing slash)."""
    return (os.environ.get("OLLAMA_HOST") or _DEFAULT_OLLAMA_URL).rstrip("/")


def vision_model() -> str:
    """Vision model tag used by the QA / scoring / pose / scene modules."""
    return os.environ.get("OLLAMA_MODEL") or _DEFAULT_VISION_MODEL
