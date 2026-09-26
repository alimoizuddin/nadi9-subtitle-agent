"""Model providers behind one interface, plus the call budget.

- ReplayProvider: answers from recorded files in replay/. Default; needs no key.
  With record_missing=True it writes the prompt to replay/pending/<key>.prompt.txt and
  raises, so a human or another model can answer offline and the run can be repeated.
- AnthropicProvider: live API (pip install anthropic; ANTHROPIC_API_KEY).
- ClaudeCliProvider: shells out to `claude -p` (uses the local Claude Code login).
- FlakyProvider: wraps any provider and fails the next N calls (tests and surprise events).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from pathlib import Path


class ModelUnavailable(Exception):
    pass


class BudgetExceeded(Exception):
    pass


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


class ReplayProvider:
    name = "replay"

    def __init__(self, directory: str | Path, record_missing: bool = False, on_drift=None):
        self.dir = Path(directory)
        self.record_missing = record_missing
        self.on_drift = on_drift

    def complete(self, key: str, prompt: str) -> str:
        f = self.dir / f"{key}.json"
        if not f.exists():
            if self.record_missing:
                pend = self.dir / "pending"
                pend.mkdir(parents=True, exist_ok=True)
                (pend / f"{key}.prompt.txt").write_text(prompt, encoding="utf-8")
            raise ModelUnavailable(f"no replay recorded for '{key}'")
        rec = json.loads(f.read_text(encoding="utf-8"))
        if rec.get("prompt_sha") != sha(prompt) and self.on_drift:
            self.on_drift(key, rec.get("prompt_sha"), sha(prompt))
        return rec["response"] if isinstance(rec["response"], str) else json.dumps(rec["response"])


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str = "claude-sonnet-5", record_dir: str | Path | None = None):
        try:
            import anthropic  # noqa: F401
        except ImportError as e:
            raise ModelUnavailable("pip install anthropic to use the live provider") from e
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise ModelUnavailable("ANTHROPIC_API_KEY not set")
        import anthropic
        self.client = anthropic.Anthropic()
        self.model = model
        self.record_dir = Path(record_dir) if record_dir else None

    def complete(self, key: str, prompt: str) -> str:
        try:
            msg = self.client.messages.create(model=self.model, max_tokens=8000,
                                              messages=[{"role": "user", "content": prompt}])
        except Exception as e:  # network, rate limit, overload
            raise ModelUnavailable(str(e)) from e
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        _record(self.record_dir, key, prompt, text, self.model)
        return text


class ClaudeCliProvider:
    name = "claude-cli"

    def __init__(self, model: str = "sonnet", record_dir: str | Path | None = None, timeout: int = 300):
        if not shutil.which("claude"):
            raise ModelUnavailable("claude CLI not on PATH")
        self.model, self.timeout = model, timeout
        self.record_dir = Path(record_dir) if record_dir else None

    def complete(self, key: str, prompt: str) -> str:
        try:
            r = subprocess.run(["claude", "-p", "--model", self.model, "--output-format", "json"],
                               input=prompt, capture_output=True, text=True, encoding="utf-8",
                               timeout=self.timeout)
        except (OSError, subprocess.TimeoutExpired) as e:
            raise ModelUnavailable(str(e)) from e
        if r.returncode != 0 or not r.stdout.strip():
            raise ModelUnavailable(f"claude CLI exit {r.returncode}: {r.stderr[:200]}")
        text = json.loads(r.stdout).get("result", "")
        _record(self.record_dir, key, prompt, text, f"claude-cli:{self.model}")
        return text


class FlakyProvider:
    """Fails the next `fail_next` calls, then delegates."""

    def __init__(self, inner, fail_next: int = 0):
        self.inner, self.fail_next = inner, fail_next
        self.name = f"{inner.name}+flaky"

    def complete(self, key: str, prompt: str) -> str:
        if self.fail_next > 0:
            self.fail_next -= 1
            raise ModelUnavailable("simulated outage (surprise event)")
        return self.inner.complete(key, prompt)


class Budget:
    def __init__(self, max_model_calls: int = 25, max_tool_calls: int = 50):
        self.max_model, self.max_tool = max_model_calls, max_tool_calls
        self.model_calls, self.tool_calls = 0, 0

    def model(self):
        if self.model_calls >= self.max_model:
            raise BudgetExceeded(f"model-call budget {self.max_model} exhausted")
        self.model_calls += 1

    def tool(self):
        if self.tool_calls >= self.max_tool:
            raise BudgetExceeded(f"tool-call budget {self.max_tool} exhausted")
        self.tool_calls += 1

    def as_dict(self):
        return {"model_calls": self.model_calls, "max_model_calls": self.max_model,
                "tool_calls": self.tool_calls, "max_tool_calls": self.max_tool}


def _record(directory, key, prompt, text, model):
    if not directory:
        return
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{key}.json").write_text(json.dumps(
        {"key": key, "prompt_sha": sha(prompt), "model": model, "response": text}, indent=2, ensure_ascii=False),
        encoding="utf-8")


def make_provider(kind: str, replay_dir, record_missing=False, on_drift=None, model=None):
    if kind == "replay":
        return ReplayProvider(replay_dir, record_missing=record_missing, on_drift=on_drift)
    if kind == "anthropic":
        return AnthropicProvider(model or "claude-sonnet-5", record_dir=replay_dir)
    if kind == "claude-cli":
        return ClaudeCliProvider(model or "sonnet", record_dir=replay_dir)
    raise ValueError(f"unknown provider {kind}")
