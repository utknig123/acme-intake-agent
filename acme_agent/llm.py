"""OpenAI-compatible chat client with tool calling, retry/backoff and model fallback.

Works with Groq (default), OpenAI, Gemini (OpenAI-compat endpoint), OpenRouter, etc.
"""
from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass, field

PRESETS = {
    "groq": ("https://api.groq.com/openai/v1", "llama-3.3-70b-versatile"),
    "openai": ("https://api.openai.com/v1", "gpt-4o-mini"),
    "gemini": ("https://generativelanguage.googleapis.com/v1beta/openai", "gemini-flash-latest"),
    "openrouter": ("https://openrouter.ai/api/v1", "meta-llama/llama-3.3-70b-instruct"),
}


class LLMError(Exception):
    pass


class RateLimited(LLMError):
    def __init__(self, msg, wait=5.0):
        super().__init__(msg)
        self.wait = wait


class ToolFormatError(LLMError):
    def __init__(self, msg, failed=""):
        super().__init__(msg)
        self.failed = failed


@dataclass
class Reply:
    content: str = ""
    tool_calls: list = field(default_factory=list)   # [{id, name, arguments(dict)}]
    model: str = ""
    usage: dict = field(default_factory=dict)


class LLM:
    def __init__(self, provider=None, model=None, api_key=None, base_url=None, fallbacks=None, sleep=time.sleep):
        self.provider = (provider or os.environ.get("LLM_PROVIDER") or "groq").lower()
        preset = PRESETS.get(self.provider, PRESETS["groq"])
        self.base = (base_url or os.environ.get("LLM_BASE_URL") or preset[0]).rstrip("/")
        self.model = model or os.environ.get("LLM_MODEL") or preset[1]
        self.key = api_key or os.environ.get("LLM_API_KEY", "")
        fb = fallbacks if fallbacks is not None else os.environ.get("LLM_FALLBACK_MODELS", "")
        self.fallbacks = [m.strip() for m in (fb.split(",") if isinstance(fb, str) else fb) if m.strip()]
        self.sleep = sleep
        self.calls = 0
        # Fallback chain across providers: primary -> Gemini (if key) -> remaining models.
        self.chain = [(self.base, self.key, self.model)]
        gkey = os.environ.get("GEMINI_API_KEY", "")
        if gkey:
            self.chain.append((PRESETS["gemini"][0], gkey, os.environ.get("GEMINI_MODEL") or PRESETS["gemini"][1]))
        self.chain += [(self.base, self.key, m) for m in self.fallbacks]
        self.stats = {}

    @property
    def configured(self):
        return bool(self.key)

    def chat(self, messages, tools=None, temperature=0.3, max_tokens=700) -> Reply:
        """Try each model in the chain; if every one is rate limited, wait for the shortest window and go again."""
        last = None
        for rnd in range(3):
            waits = []
            for base, key, model in self.chain:
                try:
                    rep = self._chat_model(base, key, model, messages, tools, temperature, max_tokens)
                    self.stats[model] = self.stats.get(model, 0) + 1
                    return rep
                except RateLimited as e:
                    last = e
                    waits.append(e.wait)
                except LLMError as e:          # incl. malformed tool call: try the next model
                    last = e
            if not waits or len(waits) < len(self.chain):
                break                          # something other than rate limiting: stop retrying
            self.sleep(min(max(min(waits), 1.0), 22.0))
        raise last or LLMError("no model available")

    def _chat_model(self, base, key, model, messages, tools, temperature, max_tokens):
        body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        if "gpt-oss" in model:
            body["reasoning_effort"] = "low"
            body["max_tokens"] = max(max_tokens, 1200)   # reasoning tokens count against the budget
        if tools:
            body["tools"], body["tool_choice"] = tools, "auto"
        raw = json.dumps(body).encode()
        err = None
        for attempt in range(3):
            req = urllib.request.Request(base + "/chat/completions", data=raw, method="POST", headers={
                "Authorization": f"Bearer {key}", "Content-Type": "application/json",
                "User-Agent": "acme-intake-agent/1.0"})
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    data = json.loads(r.read().decode())
                self.calls += 1
                return self._parse(data, model)
            except urllib.error.HTTPError as e:
                text = e.read().decode("utf-8", "replace")
                err = f"HTTP {e.code}: {text[:300]}"
                if e.code == 400 and ("tool_use_failed" in text or "failed_generation" in text):
                    failed = ""
                    try:
                        failed = json.loads(text)["error"].get("failed_generation", "")
                    except Exception:
                        pass
                    recovered = _parse_inline_tool_call(failed)
                    if recovered:
                        return Reply("", recovered, model)
                    raise ToolFormatError("model produced a malformed tool call", failed)
                if e.code in (429, 500, 502, 503, 504):
                    wait = _retry_after(e.headers.get("Retry-After"), text, attempt)
                    if e.code == 429:
                        if "per day" in text.lower():
                            wait = 3600
                        raise RateLimited(err, wait)   # let the chain move on to another model first
                    if attempt >= 2:
                        raise LLMError(err)
                    self.sleep(min(wait, 4))
                    continue
                raise LLMError(err)
            except (urllib.error.URLError, TimeoutError, OSError) as e:
                err = str(e)
                self.sleep(1 + attempt)
        raise LLMError(err or "LLM unavailable")

    @staticmethod
    def _parse(data, model):
        msg = data["choices"][0]["message"]
        calls = []
        for tc in msg.get("tool_calls") or []:
            fn = tc["function"]
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except ValueError:
                args = {"_raw": fn.get("arguments")}
            calls.append({"id": tc.get("id") or f"call_{uuid.uuid4().hex[:8]}", "name": fn["name"], "arguments": args})
        content = msg.get("content") or ""
        if not calls and "<function" in content:
            calls = _parse_inline_tool_call(content)
            content = ""
        content = re.sub(r"<think>.*?</think>", "", content, flags=re.S).strip()
        return Reply(content, calls, model, data.get("usage", {}))


def _retry_after(header, text, attempt):
    try:
        return float(header)
    except (TypeError, ValueError):
        pass
    m = re.search(r"try again in ([\d.]+)(ms|s|m)", text)
    if m:
        v = float(m.group(1))
        return v / 1000 + 0.3 if m.group(2) == "ms" else v * (60 if m.group(2) == "m" else 1) + 0.5
    return 1.5 * (attempt + 1)


_TOOL_BY_KEY = {"outcome": "end_conversation", "fields": "save_fields", "confirmed": "confirm_identity"}


def _parse_inline_tool_call(text):
    """Recover malformed tool calls: Llama '<function=name{json}</function>' and gpt-oss
    '{"name": "commentary", "arguments": {...}}' (wrong channel name) forms."""
    out = []
    try:
        obj = json.loads((text or "").strip())
        if isinstance(obj, dict) and isinstance(obj.get("arguments"), dict):
            args = obj["arguments"]
            name = obj.get("name")
            if name not in _TOOL_BY_KEY.values():
                name = next((t for k, t in _TOOL_BY_KEY.items() if k in args), None)
            if name:
                return [{"id": f"call_{uuid.uuid4().hex[:8]}", "name": name, "arguments": args}]
    except ValueError:
        pass
    for m in re.finditer(r"<function=([A-Za-z_]+)\s*>?\s*(\{.*?\})\s*(?:</function>|$|<)", text or "", re.S):
        try:
            out.append({"id": f"call_{uuid.uuid4().hex[:8]}", "name": m.group(1), "arguments": json.loads(m.group(2))})
        except ValueError:
            continue
    return out
