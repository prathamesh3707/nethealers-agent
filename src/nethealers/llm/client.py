"""One small client for any OpenAI-compatible chat API, with a fallback chain.

Providers are tried in the order of LLM_PROVIDERS (from .env):

- openrouter: free models; OpenRouter itself also falls back across the
  models listed in OPENROUTER_MODELS
- groq, gemini: their free tiers, through their OpenAI-compatible endpoints
- ollama: a model running on this laptop (no internet needed)

If every provider fails (no key, out of free quota, offline), `chat_json`
raises LLMUnavailable and the agent carries on with its offline rules.
Answers are cached on disk by prompt, so replaying a demo costs nothing.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import time
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[3]
load_dotenv(ROOT / ".env")

DEFAULT_OPENROUTER_MODELS = "nvidia/nemotron-3-super-120b-a12b:free,google/gemma-4-31b-it:free,openrouter/free"


class LLMUnavailable(RuntimeError):
    """No provider could answer."""


@dataclass(frozen=True)
class Provider:
    name: str
    base_url: str
    api_key: str
    models: tuple[str, ...]

    @property
    def configured(self) -> bool:
        return bool(self.api_key) and bool(self.models)


def providers_from_env() -> list[Provider]:
    env = os.environ
    known = {
        "openrouter": Provider("openrouter", "https://openrouter.ai/api/v1", env.get("OPENROUTER_API_KEY", ""),
                               tuple(m.strip() for m in env.get("OPENROUTER_MODELS", DEFAULT_OPENROUTER_MODELS)
                                     .split(",") if m.strip())),
        "openai": Provider("openai", "https://api.openai.com/v1", env.get("OPENAI_API_KEY", ""),
                           (env.get("OPENAI_MODEL", "") or "gpt-4.1-mini",)),
        "groq": Provider("groq", "https://api.groq.com/openai/v1", env.get("GROQ_API_KEY", ""),
                         tuple(filter(None, [env.get("GROQ_MODEL", "")]))),
        "gemini": Provider("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/",
                           env.get("GEMINI_API_KEY", ""), tuple(filter(None, [env.get("GEMINI_MODEL", "")]))),
        "ollama": Provider("ollama", env.get("OLLAMA_URL", "http://localhost:11434/v1"),
                           "ollama" if env.get("OLLAMA_MODEL") else "", tuple(filter(None, [env.get("OLLAMA_MODEL", "")]))),
    }
    order = [p.strip() for p in env.get("LLM_PROVIDERS", "openrouter,groq,gemini,ollama").split(",") if p.strip()]
    return [known[p] for p in order if p in known]


@dataclass
class Answer:
    data: dict
    provider: str
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    seconds: float = 0.0
    cached: bool = False

    @property
    def source(self) -> str:
        return f"{self.provider}:{self.model}" + (" (cached)" if self.cached else "")


@dataclass
class LLM:
    providers: list[Provider] = field(default_factory=providers_from_env)
    cache_dir: Path | None = ROOT / ".cache" / "llm"
    timeout_s: float = 40.0
    max_tokens: int = 700
    calls: int = 0
    tokens_in: int = 0
    tokens_out: int = 0
    failures: list = field(default_factory=list)
    down_for_s: float = 60.0  # after a provider fails, skip it for this long instead of waiting on it again
    _down_until: dict = field(default_factory=dict)

    @property
    def ready(self) -> list[str]:
        return [p.name for p in self.providers if p.configured]

    def chat_json(self, system: str, user: str) -> Answer:
        key = hashlib.sha256(json.dumps([system, user, [p.name for p in self.providers]]).encode()).hexdigest()[:24]
        cached = self._cache_get(key)
        if cached:
            return cached
        errors = []
        for p in self.providers:
            if not p.configured:
                continue
            if time.monotonic() < self._down_until.get(p.name, 0.0):
                errors.append(f"{p.name}: skipped (failed recently)")
                continue
            try:
                ans = self._ask(p, system, user)
            except Exception as e:  # any provider error: note it, rest it for a while, try the next one
                errors.append(f"{p.name}: {type(e).__name__}: {str(e)[:160]}")
                self._down_until[p.name] = time.monotonic() + self.down_for_s
                continue
            self.calls += 1
            self.tokens_in += ans.tokens_in
            self.tokens_out += ans.tokens_out
            self._cache_put(key, ans)
            return ans
        self.failures.append(errors or ["no provider configured"])
        raise LLMUnavailable("; ".join(errors) or "no provider configured (add a key to .env)")

    def _ask(self, p: Provider, system: str, user: str) -> Answer:
        from openai import OpenAI

        client = OpenAI(base_url=p.base_url, api_key=p.api_key, timeout=self.timeout_s, max_retries=1)
        kwargs = dict(model=p.models[0], temperature=0.2, max_tokens=self.max_tokens,
                      messages=[{"role": "system", "content": system}, {"role": "user", "content": user}])
        if p.name == "openrouter" and len(p.models) > 1:
            kwargs["extra_body"] = {"models": list(p.models)}  # OpenRouter's own fallback across models
        t0 = time.perf_counter()
        try:
            resp = client.chat.completions.create(response_format={"type": "json_object"}, **kwargs)
        except Exception:
            resp = client.chat.completions.create(**kwargs)  # some models don't take response_format
        text = (resp.choices[0].message.content or "").strip()
        data = parse_json(text)
        usage = getattr(resp, "usage", None)
        return Answer(data, p.name, getattr(resp, "model", p.models[0]) or p.models[0],
                      getattr(usage, "prompt_tokens", 0) or 0, getattr(usage, "completion_tokens", 0) or 0,
                      time.perf_counter() - t0)

    def _cache_get(self, key: str) -> Answer | None:
        if not self.cache_dir:
            return None
        f = self.cache_dir / f"{key}.json"
        if not f.exists():
            return None
        d = json.loads(f.read_text())
        return Answer(d["data"], d["provider"], d["model"], cached=True)

    def _cache_put(self, key: str, ans: Answer) -> None:
        if not self.cache_dir:
            return
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        (self.cache_dir / f"{key}.json").write_text(json.dumps(
            {"data": ans.data, "provider": ans.provider, "model": ans.model}))


def parse_json(text: str) -> dict:
    """The first JSON object in a reply, even if the model wrapped it in prose or a code fence."""
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.MULTILINE).strip()
    try:
        out = json.loads(text)
        if isinstance(out, dict):
            return out
    except json.JSONDecodeError:
        pass
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    raise ValueError(f"no JSON object in reply: {text[:120]!r}")
