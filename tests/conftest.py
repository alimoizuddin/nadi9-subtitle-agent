import shutil
from pathlib import Path

import pytest

from nadi9.llm import ModelUnavailable, ReplayProvider
from nadi9.pipeline import Agent
from nadi9.util import read_json

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "pack"
REPLAY = ROOT / "replay"
EVENTS = ROOT / "events" / "demo_events.json"


class Recording:
    """Wraps a provider and keeps every prompt it was sent."""

    def __init__(self, inner):
        self.inner, self.name, self.prompts = inner, inner.name, []

    def complete(self, key, prompt):
        self.prompts.append((key, prompt))
        return self.inner.complete(key, prompt)


class Scripted:
    name = "scripted"

    def __init__(self, responses=None):
        self.responses, self.prompts = responses or {}, []

    def complete(self, key, prompt):
        self.prompts.append((key, prompt))
        r = self.responses.get(key)
        if r is None:
            raise ModelUnavailable(f"no scripted answer for {key}")
        if isinstance(r, Exception):
            raise r
        return r


def run_agent(pack=PACK, provider=None, events=None, cfg=None):
    return Agent(pack, provider or ReplayProvider(REPLAY), events, cfg).run()


def demo_events():
    return read_json(EVENTS)["events"]


@pytest.fixture(scope="session")
def full_run():
    """The sample run: replay answers + the four demo events."""
    rec = Recording(ReplayProvider(REPLAY))
    agent = run_agent(provider=rec, events=demo_events())
    agent.recorder = rec
    return agent


@pytest.fixture(scope="session")
def learned():
    """Replay answers, no events: the knowledge state before any correction."""
    return run_agent()


@pytest.fixture
def pack_copy(tmp_path):
    dst = tmp_path / "pack"
    shutil.copytree(PACK, dst)
    return dst


def line(agent, lid):
    return next(l for l in agent.pack.episode["lines"] if l["id"] == lid)


def tok(t, src, gloss=""):
    return {"t": t, "gloss": gloss, "src": src, "evidence": []}
