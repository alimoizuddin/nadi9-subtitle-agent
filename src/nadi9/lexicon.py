"""Lexical claims: every Nadi-9 word, each candidate meaning, and which sources back it.

A meaning is never taken from one file on trust. Senses from every source are clustered by
meaning; each cluster is weighted by *independent source families*, and the family weights
come from measured agreement with the approved examples (see sources.py), not from file
size or date.
"""
from __future__ import annotations

import re

from .morph import gloss_parts
from .util import lemma, meaning_phrases, tokenize_en

FAMILY_BASE = {"correction": 1.0, "example": 0.9, "dictB": 0.85, "expert": 0.7,
               "grammar": 0.6, "interview": 0.6, "dictA": 0.5}
STRONG = {"example", "dictB", "correction"}

SENSITIVE = re.compile(r"\b(insult\w*|rude|upstart|offen\w+|furious)\b", re.I)
SOFTENER = re.compile(r"\b(jokingly|not always|context decides|playful\w*)\b", re.I)

GLOSS_ALIASES = {"NEG": "not", "Q": "question particle"}


def example_root(tok: dict, suffix_table: dict[str, str]) -> tuple[str, str] | None:
    """(root, meaning) from an example token, or None for loans."""
    lem, feats = gloss_parts(tok["g"])
    if "LOAN" in feats:
        return None
    if lem in GLOSS_ALIASES:
        lem = GLOSS_ALIASES[lem]
    word = tok["t"]
    by_feat = {v: k for k, v in suffix_table.items()}
    for f in ("RESP", "PAST", "FUT", "HORT"):
        if f in feats and f in by_feat and word.endswith(by_feat[f]):
            word = word[: -len(by_feat[f])]
    return word, lem


def _same(m1: str, m2: str) -> bool:
    return bool(meaning_phrases(m1) & meaning_phrases(m2))


def build(pack, suffix_table, excluded: set[str], agreement: dict[str, float],
          grammar_items: list[dict], corrections: list[dict]) -> dict[str, dict]:
    senses: dict[str, list[dict]] = {}

    def add(term, meaning, family, ref, pos=None):
        senses.setdefault(term, []).append({"meaning": meaning, "family": family, "ref": ref, "pos": pos})

    for e in pack.dict_a:
        add(e["term"], e["meaning"], "dictA", f"dictA:{e['id']}", e.get("pos"))
    for e in pack.dict_b:
        add(e["term"], e["meaning"], "dictB", f"dictB:{e['id']}", e.get("pos"))
    for ex in pack.examples:
        if ex["id"] in excluded:
            continue
        for tok in ex["tokens"]:
            got = example_root(tok, suffix_table)
            if got:
                add(got[0], got[1], "example", f"example:{ex['id']}", tok["pos"])
    for gi in grammar_items:
        add(gi["term"], gi["meaning"], "grammar", f"grammar:{gi.get('rule', 'note')}")
    for c in corrections:
        add(c["term"], c["meaning"], "correction", f"correction:{c['event']}")

    terms = set(senses)
    lex = {}
    for term, ss in senses.items():
        clusters: list[list[dict]] = []
        for s in ss:
            for cl in clusters:
                if any(_same(s["meaning"], o["meaning"]) for o in cl):
                    cl.append(s)
                    break
            else:
                clusters.append([s])
        lex[term] = _claim(term, clusters, agreement)

    _attach_interviews(pack, lex, suffix_table)
    _attach_experts(pack, lex)
    _attach_sensitivity(pack, lex)
    for term, claim in lex.items():
        _status(claim)
    return lex


def _claim(term, clusters, agreement):
    out = []
    for cl in clusters:
        fams = {}
        for s in cl:
            w = FAMILY_BASE[s["family"]] * agreement.get(s["family"], 1.0)
            fams.setdefault(s["family"], {"weight": w, "refs": []})["refs"].append(s["ref"])
        display = max(cl, key=lambda s: len(s["meaning"]))["meaning"]
        out.append({"meaning": display, "families": fams, "status": "LIVE",
                    "pos": next((s["pos"] for s in cl if s.get("pos")), None),
                    "all_meanings": sorted({s["meaning"] for s in cl})})
    return {"term": term, "senses": out, "flags": [], "notes": [], "attested": []}


def _lemma_seq(text: str) -> str:
    return " " + " ".join(lemma(w) for w in tokenize_en(text)) + " "


def _phrase_in(sense, seq: str, exclude: str = "") -> bool:
    """A sense is supported by a text only if one of its whole meaning phrases occurs in it.
    Word overlap is not enough: 'younger brother' must not match a line about an elder brother."""
    phrases = {p for m in sense["all_meanings"] for p in meaning_phrases(m)}
    return any(f" {p} " in seq for p in phrases if p != exclude and len(p) >= 2)


def _attach_interviews(pack, lex, suffix_table):
    sufs = sorted(suffix_table, key=len, reverse=True)
    for iv in pack.interviews:
        for i, row in enumerate(iv.get("transcript") or []):
            eng = _lemma_seq(row["english"])
            for w in re.findall(r"[a-z]+", row["nadi9"].lower()):
                root = w if w in lex else next((w[: -len(s)] for s in sufs if w.endswith(s) and w[: -len(s)] in lex), None)
                if not root:
                    continue
                ref = f"interview:{iv['id']}#{i}"
                lex[root]["attested"].append(ref)
                for sense in lex[root]["senses"]:
                    if _phrase_in(sense, eng):
                        sense["families"].setdefault("interview", {"weight": FAMILY_BASE["interview"], "refs": []})["refs"].append(ref)


def _attach_experts(pack, lex):
    for n in pack.experts:
        text = n["text"]
        seq = _lemma_seq(text)
        for term, claim in lex.items():
            if not re.search(rf"\b{re.escape(term)}\b", text):
                continue
            claim["notes"].append({"ref": f"expert:{n['id']}", "text": text})
            for sense in claim["senses"]:
                if _phrase_in(sense, seq, exclude=term):
                    sense["families"].setdefault("expert", {"weight": FAMILY_BASE["expert"], "refs": []})["refs"].append(f"expert:{n['id']}")
    for e in pack.dict_b + pack.dict_a:
        if e.get("note") and e["term"] in lex and not e["note"].startswith("[QUARANTINED"):
            lex[e["term"]]["notes"].append({"ref": f"{'dictB' if e['id'].startswith('B') else 'dictA'}:{e['id']}", "text": e["note"]})


def _attach_sensitivity(pack, lex):
    texts = [(f"expert:{n['id']}", n["text"]) for n in pack.experts]
    texts += [(f"dictB:{e['id']}", f"{e['term']} {e.get('note', '')}") for e in pack.dict_b]
    texts += [(f"feedback:{c['id']}", c["text"]) for c in pack.feedback]
    for iv in pack.interviews:
        for i, row in enumerate(iv.get("transcript") or []):
            # Only the interviewer's commentary: a word merely spoken in a rude-flagged line is not the topic.
            texts.append((f"interview:{iv['id']}#{i}", row["english"]))
    for term, claim in lex.items():
        warn, soft = [], []
        for ref, text in texts:
            if re.search(rf"\b{re.escape(term)}\b", text, re.I):
                if SOFTENER.search(text):
                    soft.append(ref)
                elif SENSITIVE.search(text):
                    warn.append(ref)
        if warn:
            claim["flags"].append({"flag": "STATUS_SENSITIVE", "refs": warn, "dissent": soft,
                                   "lead_only": [r for r in warn if r.startswith("feedback:")]})


def _status(claim):
    senses = claim["senses"]
    has_corr = any("correction" in s["families"] for s in senses)
    for s in senses:
        if has_corr and "correction" not in s["families"]:
            s["status"] = "SUPERSEDED"
    live = [s for s in senses if s["status"] == "LIVE"]
    for s in live:
        if set(s["families"]) == {"dictA"}:
            for r in live:
                if r is s:
                    continue
                n_ex = len(r["families"].get("example", {}).get("refs", []))
                if n_ex >= 2 and ("dictB" in r["families"] or "expert" in r["families"]):
                    s["status"] = "POISON_SUSPECT"
                    s["contradicted_by"] = _refs(r)
    live = [s for s in senses if s["status"] == "LIVE"]
    for s in senses:
        s["weight"] = round(sum(f["weight"] for f in s["families"].values()), 3)
    if not live:
        claim["status"], claim["meaning"] = "UNSUPPORTED", None
        return
    live.sort(key=lambda s: s["weight"], reverse=True)
    best = live[0]
    claim["meaning"] = best["meaning"]
    claim["pos"] = best.get("pos")
    fams = set(best["families"])
    if len(live) > 1:
        claim["status"] = "CONTESTED"
        claim["rivals"] = [{"meaning": r["meaning"], "refs": _refs(r)} for r in live[1:]]
    elif "correction" in fams or (len(fams) >= 2 and fams & STRONG):
        claim["status"] = "CONFIRMED"
    elif fams & STRONG or len(fams) >= 2:
        claim["status"] = "SUPPORTED"
    else:
        claim["status"] = "WEAK"
    claim["evidence"] = _refs(best)


def _refs(sense) -> list[str]:
    return [r for f in sense["families"].values() for r in f["refs"]]


def trusted_phrases(claim) -> set[str]:
    """Meanings the verifier accepts for a term: every live sense (contested terms keep both)."""
    out = set()
    for s in claim["senses"]:
        if s["status"] == "LIVE":
            for m in s["all_meanings"]:
                out |= meaning_phrases(m)
    return out
