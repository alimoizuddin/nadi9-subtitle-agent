"""Write the run's outputs. Everything an evaluator needs to see what the agent knew, when."""
from __future__ import annotations

import textwrap
from collections import Counter
from pathlib import Path

from .sources import assess
from .util import seconds_to_srt, tc_to_seconds, write_json, write_jsonl

DECISION_KEYS = ["subtitle_id", "start", "end", "speaker", "addressee", "relation", "source_text", "nadi_9_text",
                 "gloss", "confidence", "confidence_reason", "decision", "evidence", "assumptions", "conflicts",
                 "review_question", "other_questions", "checks", "model_self_confidence", "knowledge_version", "why"]


def write_all(agent, out_dir) -> dict:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    lines = agent.pack.episode["lines"]
    decisions = [agent.decisions[l["id"]] for l in lines if l["id"] in agent.decisions]

    write_jsonl(out / "subtitle_decisions.jsonl", [{k: d[k] for k in DECISION_KEYS} for d in decisions])
    (out / "subtitles.srt").write_text(_srt(decisions, agent.cfg["max_line_chars"]), encoding="utf-8")
    write_json(out / "learned_rules.json", {
        "rules": agent.rules, "rejected_model_rules": getattr(agent, "rejected_rules", []),
        "expert_positions": agent.expert_positions, "suspect_examples": agent.suspects,
        "retracted_examples": sorted(agent.retracted)})
    write_json(out / "lexicon.json", agent.lex)
    write_json(out / "source_assessment.json", assess(agent.pack, agent.agreement, agent.suspects, agent.security))
    queue = sorted((d for d in decisions if d["decision"] != "ACCEPT"),
                   key=lambda d: (d["review_priority"], d["subtitle_id"]))
    write_json(out / "review_queue.json", [{
        "subtitle_id": d["subtitle_id"], "priority": d["review_priority"], "decision": d["decision"],
        "context": f"{d['speaker']} to {d['addressee']} ({d['relation']})", "source_text": d["source_text"],
        "draft": d["nadi_9_text"], "question": d["review_question"], "also_check": d["other_questions"],
        "evidence": d["evidence"], "conflicts": d["conflicts"]} for d in queue])
    write_jsonl(out / "run_log.jsonl", agent.log_rows)
    write_json(out / "revisions.json", {"replans": agent.replans, "history": agent.history})
    summary = _summary(agent, decisions)
    (out / "final_report.md").write_text(_report(agent, decisions, queue, summary), encoding="utf-8")
    return summary


def _srt(decisions, width) -> str:
    blocks = []
    for i, d in enumerate(decisions, 1):
        if d["decision"] == "ACCEPT":
            text = d["nadi_9_text"]
        elif d["nadi_9_text"]:
            text = f"[?] {d['nadi_9_text']}"
        else:
            text = f"[NO EVIDENCE] {d['source_text']}"
        wrapped = "\n".join(textwrap.wrap(text, width)[:2])
        blocks.append(f"{i}\n{seconds_to_srt(tc_to_seconds(d['start']))} --> {seconds_to_srt(tc_to_seconds(d['end']))}\n{wrapped}\n")
    return "\n".join(blocks)


def _summary(agent, decisions) -> dict:
    c = Counter(d["decision"] for d in decisions)
    gaps = [d for d in decisions if d["model_self_confidence"] is not None and d["decision"] != "ACCEPT"]
    over = [d["subtitle_id"] for d in gaps if d["model_self_confidence"] >= 0.8]
    if not decisions:
        rec = "DO NOT RELEASE: nothing drafted"
    elif c["ACCEPT"] == len(decisions):
        rec = "RELEASE after a spot-check by a Nadi-9 speaker"
    else:
        rec = (f"DO NOT RELEASE YET: {len(decisions) - c['ACCEPT']} of {len(decisions)} lines need a Nadi-9 expert. "
               f"Send review_queue.json; {c['ACCEPT']} lines are ready.")
    return {"lines": len(decisions), "decisions": dict(c), "release_recommendation": rec,
            "model_overconfident_on": over, "budget": agent.budget.as_dict(), "knowledge_version": agent.kv}


def _report(agent, decisions, queue, s) -> str:
    L = []
    w = L.append
    w(f"# Nadi-9 subtitle run — {agent.pack.episode['title']} ({agent.pack.episode['episode_id']})\n")
    if agent.pack.manifest.get("synthetic"):
        w("> **Synthetic evidence pack.** The official STAGE pack had not arrived; see `pack/PACK_NOTICE.md`.\n")
    w(f"## Release recommendation\n\n**{s['release_recommendation']}**\n")
    w("| Decision | Lines |\n|---|---|")
    for k in ("ACCEPT", "HUMAN_REVIEW", "INSUFFICIENT_EVIDENCE"):
        w(f"| {k} | {s['decisions'].get(k, 0)} |")
    w("")
    w("## Every line\n\n| ID | Decision | Conf. | Nadi-9 | Source |\n|---|---|---|---|---|")
    for d in decisions:
        w(f"| {d['subtitle_id']} | {d['decision']} | {d['confidence']:.2f} | {d['nadi_9_text'] or '—'} | {d['source_text']} |")
    w("")
    w("## Questions for the language expert (most important first)\n")
    for q in queue:
        w(f"- **{q['subtitle_id']}** (P{q['review_priority']}): {q['review_question']}")
    w("")
    w("## What the agent learned\n\n| Rule | Status | Support | Counterexamples | Dissent |\n|---|---|---|---|---|")
    for r in agent.rules:
        w(f"| {r['id']} ({r['kind']}) | {r['status']} | {len(r['support'])} | {', '.join(r['counter']) or '—'} | {', '.join(r.get('dissent', [])) or '—'} |")
    for r in getattr(agent, "rejected_rules", []):
        w(f"| {r['id']} (model-proposed) | **{r['status']}** | {len(r['support'])} | — | — |")
    w("")
    if agent.suspects:
        w("**Approved examples the evidence contradicts:** " + "; ".join(
            f"{e} breaks {', '.join(rs)}" for e, rs in agent.suspects.items()) + ". They were excluded from evidence.\n")
    if agent.retracted:
        w(f"**Retracted during the run:** {', '.join(sorted(agent.retracted))} (already excluded as suspect "
          "before the retraction arrived).\n")
    poisoned = [(t, s_) for t, c in agent.lex.items() for s_ in c["senses"] if s_["status"] == "POISON_SUSPECT"]
    if poisoned:
        w("**Dictionary entries rejected as poisoned:**\n")
        for t, s_ in poisoned:
            w(f"- `{t}` = '{s_['meaning']}' ({', '.join(r for f in s_['families'].values() for r in f['refs'])}); "
              f"contradicted by {', '.join(s_.get('contradicted_by', []))}")
        w("")
    ag = agent.agreement
    w(f"**Source trust (measured):** Dictionary A agrees with the examples {ag['dictA']['agreement']:.0%} of the time "
      f"({ag['dictA']['checked_against_examples']} entries checked); Dictionary B {ag['dictB']['agreement']:.0%} "
      f"({ag['dictB']['checked_against_examples']} checked). Size and date were not used as trust.\n")
    w("## Surprise events and re-planning\n")
    for row in agent.log_rows:
        if row["kind"] in ("EVENT", "TOOL_FAILURE", "MODEL_UNAVAILABLE", "SECURITY_QUARANTINE", "BUDGET_EXHAUSTED"):
            w(f"- `{row['kind']}` (knowledge v{row['kv']}): {_short(row['detail'])}")
    for rp in agent.replans:
        changed = [c for c in rp["changes"] if c["changed"]]
        w(f"- Re-plan after **{rp['event']}**: {len(rp['affected'])} line(s) affected ({', '.join(rp['affected']) or 'none'}), "
          f"{len(changed)} changed, {len(rp['untouched'])} untouched.")
        for c in changed:
            w(f"  - {c['line']}: {c['before'][0]} ({c['before'][2]}) → {c['after'][0]} ({c['after'][2]})"
              + (" — redrafted" if c["redrafted"] else ""))
        for c in rp["changes"]:
            if not c["changed"] and c.get("question_changed"):
                w(f"  - {c['line']}: decision unchanged{' after redraft' if c['redrafted'] else ''}; the expert question "
                  f"narrowed from “{c['question_before']}” to “{c['question_after']}”")
    w("")
    w("## Budget\n")
    b = s["budget"]
    w(f"Model calls {b['model_calls']}/{b['max_model_calls']}, tool calls {b['tool_calls']}/{b['max_tool_calls']}.\n")
    if s["model_overconfident_on"]:
        w(f"**Model over-confidence:** the drafting model rated itself ≥0.80 on {', '.join(s['model_overconfident_on'])}, "
          "which the checker sent to review. Model self-ratings are recorded, never used.\n")
    return "\n".join(L) + "\n"


def _short(d) -> str:
    if isinstance(d, dict):
        keep = {k: v for k, v in d.items() if k not in ("patterns",)}
        s = ", ".join(f"{k}={v}" for k, v in keep.items())
    else:
        s = str(d)
    return s if len(s) < 260 else s[:257] + "..."
