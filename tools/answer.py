"""Record an offline answer for a pending prompt.

Used when no API key is available: the pipeline writes replay/pending/<key>.prompt.txt, a model
(here: Claude, in a Claude Code session) answers it, and this script stores the answer with the
prompt's hash so later runs can detect drift.

    python tools/answer.py <key> <answer-file> [--model NAME]
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from nadi9.llm import sha  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("key")
ap.add_argument("answer")
ap.add_argument("--model", default="claude-opus-5-5 (offline, Claude Code session)")
ap.add_argument("--replay-dir", default="replay")
a = ap.parse_args()

d = Path(a.replay_dir)
prompt = (d / "pending" / f"{a.key}.prompt.txt").read_text(encoding="utf-8")
answer = Path(a.answer).read_text(encoding="utf-8")
json.loads(answer)  # refuse to record something that is not JSON
(d / f"{a.key}.json").write_text(json.dumps({"key": a.key, "prompt_sha": sha(prompt), "model": a.model,
                                             "response": answer}, indent=2, ensure_ascii=False), encoding="utf-8")
(d / "pending" / f"{a.key}.prompt.txt").unlink()
print(f"recorded replay/{a.key}.json")
