"""Turn a verification result into a decision, a calibrated confidence with a reason, and one
precise question for the language expert."""
from __future__ import annotations

from .prompts import relation

ACCEPT_AT = 0.80

# Most important first: this is the order in which a reviewer should see the issues.
PRIORITY = ["INJECTION", "GAP", "POISON_USE", "UNSUPPORTED_TERM", "UNSUPPORTED_MORPHEME", "MEANING_MISMATCH",
            "RESPECT_RISK", "RESPECT", "OMISSION", "ADDITION", "GRAMMAR", "PARTIAL_GAP", "CONTESTED", "LOAN_DISSENT",
            "SINGLE_SOURCE_MORPHEME", "DROPPED", "WEAK_TERM", "TIMING", "FORMAT", "NUMBERS", "NAMES"]


def decide(line, chars, proposal, res, setting) -> dict:
    fails, blocking = res.fails, res.blocking
    penalties = sorted((c for c in res.checks if c["penalty"]), key=lambda c: -c["penalty"])
    conf = 0.95 - sum(c["penalty"] for c in penalties)
    if fails:
        conf = min(conf, 0.3)
    conf = round(max(0.05, min(conf, 0.95)), 2)

    if proposal.get("nadi_9_text") is None:
        decision, conf = "INSUFFICIENT_EVIDENCE", 0.0
        reason = "No translation proposed: " + "; ".join(
            f"'{g.get('words')}' ({g.get('reason', 'no evidence')})" for g in proposal.get("gaps") or [])
    elif fails:
        decision = "HUMAN_REVIEW"
        reason = "Checker rejected the draft: " + "; ".join(c["detail"] for c in fails[:3])
    elif blocking:
        decision = "HUMAN_REVIEW"
        reason = "Needs expert judgement: " + "; ".join(c["detail"] for c in blocking[:3])
    elif conf >= ACCEPT_AT:
        decision = "ACCEPT"
        reason = "All tokens and rules supported" + (
            "; minor: " + "; ".join(c["detail"] for c in penalties[:2]) if penalties else " by at least two independent sources")
    else:
        decision = "HUMAN_REVIEW"
        reason = "Low evidence strength: " + "; ".join(c["detail"] for c in penalties[:3])

    issues = sorted(fails + blocking, key=lambda c: PRIORITY.index(c["kind"]) if c["kind"] in PRIORITY else 99)
    questions = [q for q in (_question(c, line, chars, proposal, setting) for c in issues) if q]
    seen, uniq = set(), []
    for q in questions:
        if q not in seen:
            seen.add(q)
            uniq.append(q)
    return {"decision": decision, "confidence": conf, "confidence_reason": reason,
            "review_question": uniq[0] if uniq and decision != "ACCEPT" else None,
            "other_questions": uniq[1:] if decision != "ACCEPT" else [],
            "priority": _priority(issues)}


def _priority(issues) -> int:
    kinds = {c["kind"] for c in issues}
    if kinds & {"INJECTION", "POISON_USE", "RESPECT_RISK", "RESPECT"}:
        return 1
    if kinds & {"GAP", "PARTIAL_GAP", "UNSUPPORTED_TERM", "MEANING_MISMATCH", "CONTESTED", "OMISSION"}:
        return 2
    return 3 if kinds else 4


def _question(c, line, chars, proposal, setting) -> str | None:
    s, a = chars[line["speaker"]], chars[line["addressee"]]
    who = f"{s['name']} ({s['age']}) to {a['name']} ({a['age']}, {relation(s, a)})"
    src = line["text"]
    k = c["kind"]
    if k == "PARTIAL_GAP":
        return (f"The draft of '{src}' ({who}) has no evidence for '{c['data']['words']}' "
                f"({c['data']['reason'].rstrip('.')}). What is the Nadi-9 for it, or can it be left out?")
    if k == "GAP":
        gaps = proposal.get("gaps") or []
        if any("model unavailable" in (g.get("reason") or "") for g in gaps):
            return f"'{src}' was not drafted because the model was unavailable. Re-run, or translate it manually."
        words = ", ".join(f"'{g.get('words')}'" for g in gaps) or c["detail"]
        idiom = any("idiom" in (g.get("reason") or "").lower() for g in gaps)
        if idiom:
            return (f"'{src}' ({who}) is an idiom and the pack has no Nadi-9 idioms. Is there a Nadi-9 expression "
                    f"for this, or should the subtitle keep the literal image?")
        return f"The pack has no evidence for {words} in '{src}' ({who}). What is the Nadi-9 wording here?"
    d = c.get("data") or {}
    if k == "RESPECT_RISK":
        direction = f" The script says: '{line['direction']}'" if line.get("direction") else ""
        return (f"{s['name']} ({s['age']}) calls {a['name']} ({a['age']}) '{d['term']}'. {', '.join(d['against'])} say this "
                f"is an insult toward an elder; {', '.join(d['dissent']) or 'no source'} says it can be playful.{direction} "
                f"Keep '{d['term']}' for the teasing, or use a respectful form of address?")
    if k == "CONTESTED":
        rivals = "; ".join(f"'{r['meaning']}' ({', '.join(r['refs'])})" for r in d["rivals"])
        return (f"'{d['term']}' is '{d['meaning']}' in {', '.join(d['evidence'])} but {rivals}. "
                f"Which meaning fits '{src}' ({who})?")
    if k == "LOAN_DISSENT":
        return (f"The scene is set in: {setting}. '{d['loan']}' is kept unchanged per {d['rule']}, but "
                f"{', '.join(d['dissent'])} says rural speech adds '-u' (busu, phonu). Which form do these characters use?")
    if k == "SINGLE_SOURCE_MORPHEME":
        return (f"Is '{d['token']}' (with '-{d['suffix']}', {d['feature']}) a real form? Only {', '.join(d['sources'])} "
                f"support the suffix. If not, how is '{src}' said?")
    if k == "WEAK_TERM":
        return (f"Is '{d['term']}' the right word for '{d['meaning']}' in '{src}'? "
                f"Only {', '.join(d['evidence'])} supports it.")
    if k == "DROPPED":
        return (f"The draft of '{src}' leaves out '{d['words']}' ({d['reason'].rstrip('.')}). Is that acceptable, "
                f"or what is the Nadi-9 for it?")
    if k == "TIMING":
        return f"'{src}' is on screen too briefly: {c['detail']}. Extend the timing, merge with the next line, or shorten?"
    if k in ("UNSUPPORTED_TERM", "UNSUPPORTED_MORPHEME", "MEANING_MISMATCH", "POISON_USE", "GRAMMAR",
             "RESPECT", "OMISSION", "ADDITION"):
        return f"The checker rejected the draft for '{src}' ({who}): {c['detail']}. What is the correct form?"
    return None
