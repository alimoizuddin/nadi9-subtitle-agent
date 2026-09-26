"""Inspect the evidence: what each source is, and how far it can be trusted.

Precedence is *measured*, not assumed from size or date. Each dictionary is scored by how
often its entries agree with the approved examples (excluding examples the rule tests have
flagged as suspect). The weights used by lexicon.py are FAMILY_BASE x measured agreement.
"""
from __future__ import annotations

from .lexicon import _same, example_root

POLICY = [
    ("correction", "Named linguist correction received during the run. Highest, but logged and reversible."),
    ("example", "Approved examples, unless a well-supported rule marks one as suspect."),
    ("dictB", "Community dictionary. Weighted by measured agreement with examples."),
    ("expert", "Expert notes. Kept visible when experts disagree; can add caution, never remove it."),
    ("grammar", "Grammar note. Every rule is tested against examples before use."),
    ("interview", "Interview transcripts. The interviewer's translation is loose: supports, never decides."),
    ("dictA", "Vendor dictionary. Largest file, weighted by measured agreement; single-source meanings go to review."),
    ("feedback", "Viewer feedback. Never evidence for a word. Can raise the priority of a review."),
    ("model", "Model output. Never evidence. Every claim it makes is checked against the sources above."),
]


def dictionary_agreement(pack, suffix_table, excluded) -> dict:
    ex_senses: dict[str, list[tuple[str, str]]] = {}
    for ex in pack.examples:
        if ex["id"] in excluded:
            continue
        for tok in ex["tokens"]:
            got = example_root(tok, suffix_table)
            if got:
                ex_senses.setdefault(got[0], []).append((got[1], ex["id"]))
    out = {}
    for name, entries in (("dictA", pack.dict_a), ("dictB", pack.dict_b)):
        checked, agree, disagree = 0, 0, []
        for e in entries:
            if e["term"] not in ex_senses:
                continue
            checked += 1
            if any(_same(e["meaning"], m) for m, _ in ex_senses[e["term"]]):
                agree += 1
            else:
                disagree.append({"entry": f"{name}:{e['id']}", "term": e["term"], "says": e["meaning"],
                                 "examples_say": sorted({m for m, _ in ex_senses[e["term"]]}),
                                 "examples": sorted({i for _, i in ex_senses[e["term"]]})})
        out[name] = {"entries": len(entries), "checked_against_examples": checked,
                     "agreement": round(agree / checked, 3) if checked else None,
                     "disagreements": disagree}
    return out


def assess(pack, agreement: dict, suspects: dict, security_log: list) -> dict:
    by_id = {s["id"]: s for s in pack.manifest["sources"]}
    return {
        "precedence_policy": [{"family": f, "rule": r} for f, r in POLICY],
        "sources": {
            "examples": {**by_id["examples"], "count": len(pack.examples),
                         "suspect": suspects},
            "dictA": {**by_id["dictA"], **agreement["dictA"]},
            "dictB": {**by_id["dictB"], **agreement["dictB"]},
            "grammar": {**by_id["grammar"], "note": "rules tested individually; see learned_rules.json"},
            "experts": {**by_id["experts"], "count": len(pack.experts),
                        "experts": sorted({n["expert"] for n in pack.experts})},
            "interviews": {**by_id["interviews"], "count": len(pack.interviews),
                           "without_transcript": [iv["id"] for iv in pack.interviews if not iv.get("transcript")]},
            "feedback": {**by_id["feedback"], "count": len(pack.feedback), "use": "leads only"},
        },
        "security_events": security_log,
        "not_trusted_because": {
            "largest_file": "dictA has the most entries but the lowest measured agreement",
            "newest_file": "X3 is the newest expert note; recency does not outrank agreement",
        },
    }
