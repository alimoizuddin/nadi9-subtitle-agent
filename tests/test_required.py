"""The four behaviours the brief requires tests for: conflict, unsupported term, correction, tool failure."""
from conftest import Scripted, line, run_agent, tok

from nadi9 import decide, verify


def _check(agent, lid, text, tokens, **extra):
    ln = line(agent, lid)
    prop = {"nadi_9_text": text, "tokens": tokens, **extra}
    res = verify.verify(ln, agent.chars, prop, agent.lex, agent.rules, agent.cfg)
    return res, decide.decide(ln, agent.chars, prop, res, "rural")


def test_conflict_stays_visible(learned):
    tamba = learned.lex["tamba"]
    assert tamba["status"] == "CONTESTED"
    assert any("dictA:A13" in r["refs"] for r in tamba["rivals"])
    # a draft that relies on the contested word is held for review, with both sides named
    res, d = _check(learned, "S003", "putu, tu tamba ke veluri",
                    [tok("putu", ["son"]), tok("tu", []), tok("tamba", ["home"]), tok("ke", []),
                     tok("veluri", ["welcome"])])
    assert any(c["kind"] == "CONTESTED" and c["blocking"] for c in res.checks)
    assert d["decision"] != "ACCEPT"
    assert any("dictA:A13" in c and "dictB:B08" in c for c in res.conflicts)


def test_unsupported_term_is_rejected(learned):
    res, d = _check(learned, "S001", "anno, tuvan zorbu ka",
                    [tok("anno", ["elder", "brother"]), tok("tuvan", ["you"]), tok("zorbu", ["came", "back"]),
                     tok("ka", ["?"])])
    assert any(c["kind"] == "UNSUPPORTED_TERM" for c in res.fails)
    assert d["decision"] != "ACCEPT"


def test_unsupported_suffix_is_rejected(learned):
    # '-lu' is the plural the model invented (EV1); it must not parse as a real suffix
    res, _ = _check(learned, "S002", "ma 3 sanulu pisu veluri",
                    [tok("ma", ["I"]), tok("3", ["3"]), tok("sanulu", ["years"]), tok("pisu", ["after"]),
                     tok("veluri", ["came", "back"])])
    assert any(c["kind"] == "UNSUPPORTED_MORPHEME" for c in res.fails)


def test_correction_event_is_selective(full_run, learned):
    ev3 = next(r for r in full_run.replans if r["event"] == "EV3")
    assert ev3["affected"] == ["S003"]
    # lines drafted before EV3 and not affected keep exactly what they had without the event
    for lid in ev3["untouched"]:
        assert full_run.decisions[lid]["nadi_9_text"] == learned.decisions[lid]["nadi_9_text"]
        assert full_run.decisions[lid]["decision"] == learned.decisions[lid]["decision"]
    tamba = full_run.lex["tamba"]
    assert tamba["status"] == "CONFIRMED"
    assert any(s["status"] == "SUPERSEDED" and "dictA:A13" in str(s["families"]) for s in tamba["senses"])
    ev4 = next(r for r in full_run.replans if r["event"] == "EV4")
    assert ev4["affected"] == []
    assert any(r["kind"] == "RETRACTION_ALREADY_HANDLED" for r in full_run.log_rows)


def test_model_outage_is_survived():
    agent = run_agent(provider=Scripted({}))  # every call raises ModelUnavailable
    assert len(agent.decisions) == 18
    assert all(d["nadi_9_text"] is None for d in agent.decisions.values())
    assert all(d["decision"] in ("INSUFFICIENT_EVIDENCE", "HUMAN_REVIEW") for d in agent.decisions.values())
    assert any(r["kind"] == "MODEL_GAVE_UP" for r in agent.log_rows)


def test_model_outage_retry_succeeds(full_run):
    calls = [(r["kind"], r["detail"].get("attempt")) for r in full_run.log_rows
             if r["kind"] in ("MODEL_CALL", "MODEL_UNAVAILABLE") and r["detail"].get("key") == "translate_SC1"]
    assert calls == [("MODEL_UNAVAILABLE", 1), ("MODEL_CALL", 2)]


def test_transcription_tool_failure_is_recorded(full_run):
    assert [f["target"] for f in full_run.tool_failures] == ["I3"]
    assert "status and respect" in full_run.tool_failures[0]["impact"]
