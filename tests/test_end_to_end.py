"""The CLI produces the full submission output, deterministically."""
import json
from collections import Counter

from conftest import EVENTS, REPLAY

from nadi9.cli import main

FILES = ["subtitles.srt", "subtitle_decisions.jsonl", "learned_rules.json", "review_queue.json", "final_report.md",
         "lexicon.json", "source_assessment.json", "run_log.jsonl", "revisions.json"]
FIELDS = ["subtitle_id", "source_text", "nadi_9_text", "confidence", "confidence_reason", "decision", "evidence",
          "assumptions", "conflicts", "review_question"]


def _run(pack, out):
    assert main(["run", "--pack", str(pack), "--out", str(out), "--events", str(EVENTS),
                 "--replay-dir", str(REPLAY)]) == 0
    return [json.loads(x) for x in (out / "subtitle_decisions.jsonl").read_text(encoding="utf-8").splitlines()]


def test_cli_end_to_end(pack_copy, tmp_path):
    rows = _run(pack_copy, tmp_path / "out")
    for f in FILES:
        assert (tmp_path / "out" / f).stat().st_size > 0, f
    assert len(rows) == 18 and all(set(FIELDS) <= set(r) for r in rows)
    assert Counter(r["decision"] for r in rows) == {"ACCEPT": 5, "HUMAN_REVIEW": 9, "INSUFFICIENT_EVIDENCE": 4}
    assert [r["subtitle_id"] for r in rows if r["decision"] == "ACCEPT"] == ["S001", "S002", "S004", "S007", "S010"]
    for r in rows:
        if r["decision"] == "ACCEPT":
            assert r["confidence"] >= 0.8 and r["review_question"] is None
        else:
            assert r["review_question"]
    srt = (tmp_path / "out" / "subtitles.srt").read_text(encoding="utf-8")
    assert "00:00:04,200 --> 00:00:06,800\nanno, tuvan veluriji ka" in srt
    assert "[NO EVIDENCE] Welcome home, son." in srt


def test_run_is_deterministic(pack_copy, tmp_path):
    assert _run(pack_copy, tmp_path / "a") == _run(pack_copy, tmp_path / "b")


def test_replay_matches_current_prompts():
    """Recorded answers were made for exactly the prompts the code sends today."""
    from conftest import demo_events, run_agent
    from nadi9.llm import ReplayProvider
    drift = []
    run_agent(provider=ReplayProvider(REPLAY, on_drift=lambda *a: drift.append(a[0])), events=demo_events())
    assert drift == []
