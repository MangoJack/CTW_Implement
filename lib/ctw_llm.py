# CTW Implement — LLM Client
"""
OpenAI-compatible LLM client that reads OpenClaw configuration for model
and auth details. Falls back to environment variables when running standalone.

Priority:
  1. OpenClaw config (~/.openclaw/agents/main/agent/)
  2. Environment variables (CTW_LLM_API_KEY, CTW_LLM_BASE_URL, CTW_LLM_MODEL)
  3. Hardcoded defaults (no auth — will fail with clear error)
"""
import os
import json
import logging
from pathlib import Path
from typing import Optional
from urllib.request import Request, urlopen
from urllib.error import URLError

logger = logging.getLogger("ctw_llm")

# OpenClaw config paths
_OPENCLAW_HOME = os.path.join(os.path.expanduser("~"), ".openclaw")
_AGENT_CONFIG = os.path.join(_OPENCLAW_HOME, "agents", "main", "agent")


def _load_openclaw_config() -> dict:
    """Load OpenClaw model and auth config, return empty dict if not found."""
    result = {}
    models_path = os.path.join(_AGENT_CONFIG, "models.json")
    auth_path = os.path.join(_AGENT_CONFIG, "auth-profiles.json")
    main_config = os.path.join(_OPENCLAW_HOME, "openclaw.json")

    try:
        if os.path.exists(models_path):
            with open(models_path, "r", encoding="utf-8") as f:
                result["models"] = json.load(f)
    except Exception:
        pass

    try:
        if os.path.exists(auth_path):
            with open(auth_path, "r", encoding="utf-8") as f:
                result["auth"] = json.load(f)
    except Exception:
        pass

    try:
        if os.path.exists(main_config):
            with open(main_config, "r", encoding="utf-8") as f:
                cfg = json.load(f)
            defaults = cfg.get("agents", {}).get("defaults", {})
            result["default_model"] = defaults.get("model", {}).get("primary", "")
    except Exception:
        pass

    return result


class LLMClient:
    """OpenAI-compatible chat completion client.

    Usage:
        client = LLMClient()
        response = client.chat([
            {"role": "system", "content": "You classify content."},
            {"role": "user", "content": "Classify: ..."},
        ])
        print(response)  # plain text response
    """

    def __init__(self, model: str = None, base_url: str = None,
                 api_key: str = None, provider: str = None):
        openclaw = _load_openclaw_config()

        # Resolve model: arg > env > openclaw.json > hardcoded fallback
        if model:
            self.model = model
        else:
            self.model = os.environ.get("CTW_LLM_MODEL", "")
        if not self.model:
            self.model = openclaw.get("default_model", "")
        if not self.model:
            self.model = "deepseek/deepseek-chat"
        # Strip provider prefix for API calls (deepseek/deepseek-v4-Pro → deepseek-v4-Pro)
        if "/" in self.model:
            self.provider_name, self.model_id = self.model.split("/", 1)
        else:
            self.provider_name = provider or ""
            self.model_id = self.model

        # Normalize model_id by matching against known provider models (case-insensitive)
        self.model_id = self._normalize_model_id(openclaw, self.provider_name, self.model_id)

        # Resolve API key
        if api_key:
            self.api_key = api_key
        else:
            self.api_key = os.environ.get("CTW_LLM_API_KEY", "")
        if not self.api_key:
            self.api_key = self._resolve_api_key(openclaw, self.provider_name)

        # Resolve base URL
        if base_url:
            self.base_url = base_url.rstrip("/")
        else:
            self.base_url = os.environ.get("CTW_LLM_BASE_URL", "")
        if not self.base_url:
            self.base_url = self._resolve_base_url(openclaw, self.provider_name)

    def _normalize_model_id(self, openclaw: dict, provider: str, model_id: str) -> str:
        """Match model_id against provider models to get correct casing."""
        models_cfg = openclaw.get("models", {})
        providers = models_cfg.get("providers", {})
        provider_cfg = providers.get(provider, {})
        for m in provider_cfg.get("models", []):
            if m.get("id", "").lower() == model_id.lower():
                return m["id"]
        return model_id

    def _resolve_api_key(self, openclaw: dict, provider: str) -> str:
        """Extract API key from OpenClaw auth profiles."""
        auth = openclaw.get("auth", {})
        profiles = auth.get("profiles", {})
        # Try matching provider name
        for name, profile in profiles.items():
            if profile.get("provider") == provider:
                return profile.get("key") or profile.get("token") or ""
        # Fallback: return first available key
        for profile in profiles.values():
            key = profile.get("key") or profile.get("token")
            if key:
                return key
        return ""

    def _resolve_base_url(self, openclaw: dict, provider: str) -> str:
        """Extract base URL from OpenClaw model config."""
        models_cfg = openclaw.get("models", {})
        providers = models_cfg.get("providers", {})
        provider_cfg = providers.get(provider, {})
        url = provider_cfg.get("baseUrl", "")
        if url:
            return url.rstrip("/")
        # Fallback: search all providers for the model
        for pname, pcfg in providers.items():
            for m in pcfg.get("models", []):
                if m.get("id") == self.model_id:
                    return pcfg.get("baseUrl", "").rstrip("/")
        return "https://api.deepseek.com/v1"

    def chat(self, messages: list[dict], temperature: float = 0.3,
             max_tokens: int = 4096, timeout: int = 60) -> str:
        """Send chat completion request and return the response text.

        Raises RuntimeError if no API key is configured.
        """
        if not self.api_key:
            raise RuntimeError(
                "CTW LLM: no API key configured. Set CTW_LLM_API_KEY env var "
                "or ensure OpenClaw config is at ~/.openclaw/agents/main/agent/"
            )

        url = f"{self.base_url}/chat/completions"
        body = json.dumps({
            "model": self.model_id,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }).encode("utf-8")

        req = Request(url, data=body, headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        })

        try:
            with urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            content = message.get("content", "")
            # V4 Pro / reasoning models may put answer in reasoning_content
            if not content:
                content = message.get("reasoning_content", "")
            usage = data.get("usage", {})
            logger.info(
                "LLM call: model=%s tokens_in=%s tokens_out=%s",
                self.model_id,
                usage.get("prompt_tokens", "?"),
                usage.get("completion_tokens", "?"),
            )
            return content
        except URLError as e:
            raise RuntimeError(f"CTW LLM API call failed: {e}") from e

    def classify(self, prompt: str, content_types: list[str],
                 temperature: float = 0.1) -> str:
        """Convenience: classify content into one of the given types."""
        types_list = "\n".join(f"- {t}" for t in content_types)
        messages = [
            {"role": "system", "content": (
                "You are a content classifier. Classify the given content into "
                "EXACTLY ONE of the following types. Reply with only the type "
                "identifier (the part before the colon), nothing else.\n\n"
                f"{types_list}"
            )},
            {"role": "user", "content": prompt},
        ]
        return self.chat(messages, temperature=temperature, max_tokens=64).strip()

    def generate(self, system_prompt: str, user_prompt: str,
                 temperature: float = 0.3, max_tokens: int = 4096) -> str:
        """Convenience: general content generation."""
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        return self.chat(messages, temperature=temperature, max_tokens=max_tokens)


# Module-level default instance
_default_client: Optional[LLMClient] = None


def get_client() -> LLMClient:
    """Get or create the default LLM client (lazy singleton)."""
    global _default_client
    if _default_client is None:
        _default_client = LLMClient()
    return _default_client
