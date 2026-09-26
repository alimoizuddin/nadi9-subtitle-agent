"""Command line: `python -m nadi9 run --pack pack --out sample_run`."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .llm import ModelUnavailable, make_provider
from .pipeline import DEFAULT_CFG, Agent
from .report import write_all
from .util import read_json


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="nadi9", description="Evidence-grounded Nadi-9 subtitle agent")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the full pipeline on an evidence pack")
    r.add_argument("--pack", default="pack")
    r.add_argument("--out", default="sample_run")
    r.add_argument("--events", help="JSON file of surprise events to inject during the run")
    r.add_argument("--provider", default="replay", choices=["replay", "anthropic", "claude-cli"])
    r.add_argument("--model", help="model id for live providers")
    r.add_argument("--replay-dir", default="replay")
    r.add_argument("--record-missing", action="store_true",
                   help="replay mode: write prompts with no recorded answer to replay/pending/")
    r.add_argument("--max-model-calls", type=int, default=DEFAULT_CFG["max_model_calls"])
    r.add_argument("--max-tool-calls", type=int, default=DEFAULT_CFG["max_tool_calls"])
    a = ap.parse_args(argv)

    drift = []
    try:
        provider = make_provider(a.provider, Path(a.replay_dir), a.record_missing,
                                 on_drift=lambda k, old, new: drift.append(k), model=a.model)
    except ModelUnavailable as e:
        print(f"provider unavailable: {e}", file=sys.stderr)
        return 2
    events = read_json(a.events)["events"] if a.events else []
    agent = Agent(a.pack, provider, events, {"max_model_calls": a.max_model_calls, "max_tool_calls": a.max_tool_calls})
    agent.run()
    if drift:
        agent.log("REPLAY_PROMPT_DRIFT", {"keys": drift, "note": "recorded answers were made for a different prompt"})
    s = write_all(agent, a.out)
    print(f"{s['lines']} lines: {s['decisions']}")
    print(s["release_recommendation"])
    print(f"model calls {s['budget']['model_calls']}/{s['budget']['max_model_calls']}, "
          f"tool calls {s['budget']['tool_calls']}/{s['budget']['max_tool_calls']}")
    if drift:
        print(f"warning: replay prompt drift on {drift}")
    pending = Path(a.replay_dir) / "pending"
    if a.record_missing and pending.exists() and any(pending.iterdir()):
        print(f"prompts awaiting answers: {sorted(p.name for p in pending.iterdir())}")
    print(f"outputs in {a.out}/")
    return 0
