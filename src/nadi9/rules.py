"""Grammar hypotheses: a tiny rule DSL, and code that tests each rule against the examples.

Hypotheses come from the model reading the grammar note and expert notes. The model's
output is never trusted as a rule: each hypothesis must quote its source text verbatim,
and is then tested against every approved example. Counterexamples are recorded, not
ignored. A rule the model states with no support is rejected.
"""
from __future__ import annotations

import re

from .morph import gloss_parts

KINDS = {
    "verb_final", "neg_before_verb", "tense_suffix", "resp_suffix", "resp_pronoun",
    "question_final", "loan_unchanged", "postposition_after_noun", "possessive_suffix",
    "hortative_suffix", "plural_suffix",
}

ACTIVE = {"SUPPORTED", "SUPPORTED_SUSPECT_COUNTER", "WEAK", "DOCUMENTED_UNTESTED", "SINGLE_SOURCE"}
TRUSTED = {"SUPPORTED", "SUPPORTED_SUSPECT_COUNTER"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s.replace("*", "")).strip().lower()


def quote_ok(quote: str, source_text: str) -> bool:
    q = _norm(quote)
    return len(q) >= 8 and q in _norm(source_text)


# --- per-kind testers: return 'support' | 'counter' | None (not applicable) -----------------

def _verb_idx(tokens):
    return [i for i, t in enumerate(tokens) if t["pos"] == "V"]


def _t_verb_final(ex, p):
    toks = [t for t in ex["tokens"] if t["pos"] != "PART" or t["g"] != "Q"]
    if not _verb_idx(ex["tokens"]):
        return None
    return "support" if toks and toks[-1]["pos"] == "V" else "counter"


def _t_neg_before_verb(ex, p):
    toks = ex["tokens"]
    for i, t in enumerate(toks):
        if t["t"] == p["particle"]:
            return "support" if i + 1 < len(toks) and toks[i + 1]["pos"] == "V" else "counter"
    return None


def _t_tense_suffix(ex, p):
    res = None
    for t in ex["tokens"]:
        if t["pos"] != "V":
            continue
        _, feats = gloss_parts(t["g"])
        if p["feature"] in feats:
            word = t["t"][:-2] if t["t"].endswith("ji") and "RESP" in feats else t["t"]
            if not word.endswith(p["suffix"]):
                return "counter"
            res = "support"
    return res


def _t_resp_suffix(ex, p):
    res = None
    for t in ex["tokens"]:
        if t["pos"] != "V" or "subj" not in t:
            continue
        has = t["t"].endswith(p["suffix"])
        if t["subj"] == "elder" and not has:
            return "counter"
        if t["subj"] != "elder" and has:
            return "counter"
        res = "support"
    return res


def _t_resp_pronoun(ex, p):
    status = ex.get("addressee_status")
    for t in ex["tokens"]:
        if t["pos"] == "PRON" and gloss_parts(t["g"])[0] == "you":
            want = p["elder"] if status == "elder" else p["other"]
            return "support" if t["t"] == want else "counter"
    return None


def _t_question_final(ex, p):
    is_q = ex["source"].strip().endswith("?")
    last = ex["tokens"][-1]["t"] if ex["tokens"] else ""
    if is_q:
        return "support" if last == p["particle"] else "counter"
    return "counter" if last == p["particle"] else None


def _t_loan_unchanged(ex, p):
    res = None
    for t in ex["tokens"]:
        lemma, feats = gloss_parts(t["g"])
        if "LOAN" in feats:
            if t["t"] != lemma:
                return "counter"
            res = "support"
    return res


def _t_postposition(ex, p):
    res = None
    toks = ex["tokens"]
    for i, t in enumerate(toks):
        if t["pos"] == "POST":
            if i == 0 or toks[i - 1]["pos"] not in ("N", "PRON", "NUM"):
                return "counter"
            res = "support"
    return res


def _t_suffix_feature(feature):
    def f(ex, p):
        for t in ex["tokens"]:
            _, feats = gloss_parts(t["g"])
            if feature in feats:
                return "support" if t["t"].endswith(p["suffix"]) else "counter"
        return None
    return f


TESTERS = {
    "verb_final": _t_verb_final,
    "neg_before_verb": _t_neg_before_verb,
    "tense_suffix": _t_tense_suffix,
    "resp_suffix": _t_resp_suffix,
    "resp_pronoun": _t_resp_pronoun,
    "question_final": _t_question_final,
    "loan_unchanged": _t_loan_unchanged,
    "postposition_after_noun": _t_postposition,
    "possessive_suffix": _t_suffix_feature("POSS"),
    "hortative_suffix": _t_suffix_feature("HORT"),
    "plural_suffix": _t_suffix_feature("PL"),
}


def _attested_in_interviews(rule, interviews, terms) -> list[str]:
    """For suffix rules: is root+suffix heard in natural speech?"""
    suf = rule["params"].get("suffix")
    if not suf or rule["kind"] not in ("hortative_suffix", "possessive_suffix", "plural_suffix"):
        return []
    hits = []
    for iv in interviews:
        for i, row in enumerate(iv.get("transcript") or []):
            for w in re.findall(r"[a-z]+", row["nadi9"].lower()):
                if w.endswith(suf) and w[: -len(suf)] in terms:
                    hits.append(f"interview:{iv['id']}#{i}")
    return sorted(set(hits))


def test_rule(rule: dict, examples: list[dict], excluded: set[str], interviews, terms) -> dict:
    tester = TESTERS.get(rule["kind"])
    support, counter = [], []
    if tester:
        for ex in examples:
            if ex["id"] in excluded:
                continue
            r = tester(ex, rule["params"])
            if r == "support":
                support.append(ex["id"])
            elif r == "counter":
                counter.append(ex["id"])
    rule["support"], rule["counter"] = support, counter
    rule["attested"] = _attested_in_interviews(rule, interviews, terms)

    n, c = len(support), len(counter)
    documented = rule["source"] == "grammar"
    if not tester:
        rule["status"] = "UNTESTABLE"
    elif n >= 3 and c == 0:
        rule["status"] = "SUPPORTED"
    elif n >= 3 and c <= max(1, int(0.2 * n)):
        rule["status"] = "SUPPORTED_SUSPECT_COUNTER"
    elif c > 0:
        rule["status"] = "CONTESTED"
    elif n > 0:
        rule["status"] = "WEAK"
    elif documented:
        rule["status"] = "DOCUMENTED_UNTESTED"
    elif rule["attested"] or rule["source"] == "expert":
        rule["status"] = "SINGLE_SOURCE"
    else:
        rule["status"] = "REJECTED_UNSUPPORTED"
    return rule


def suspect_examples(rules: list[dict]) -> dict[str, list[str]]:
    """Examples that break a rule otherwise well supported. The example is doubted, not the rule."""
    out: dict[str, list[str]] = {}
    for r in rules:
        if r["status"] == "SUPPORTED_SUSPECT_COUNTER":
            for ex in r["counter"]:
                out.setdefault(ex, []).append(r["id"])
    return out


def suffix_table(rules: list[dict]) -> dict[str, str]:
    feat = {"tense_suffix": None, "resp_suffix": "RESP", "hortative_suffix": "HORT",
            "possessive_suffix": "POSS", "plural_suffix": "PL"}
    table = {}
    for r in rules:
        if r["kind"] in feat and r["status"] in ACTIVE:
            f = r["params"].get("feature") if r["kind"] == "tense_suffix" else feat[r["kind"]]
            table[r["params"]["suffix"]] = f
    return table


def rule_by_kind(rules, kind, **params):
    for r in rules:
        if r["kind"] == kind and all(r["params"].get(k) == v for k, v in params.items()):
            return r
    return None


def normalise_hypotheses(raw: list[dict], sources: dict[str, str], log) -> list[dict]:
    """Validate model-extracted hypotheses. Each must use a known kind and quote its source."""
    out = []
    for h in raw:
        hid = h.get("id") or f"H{len(out) + 1}"
        cite = h.get("cites", "grammar")
        text = sources.get(cite, "")
        reason = None
        if h.get("kind") not in KINDS:
            reason = f"unknown rule kind '{h.get('kind')}'"
        elif not quote_ok(h.get("quote", ""), text):
            reason = "quote not found verbatim in cited source"
        if reason:
            log("RULE_EXTRACTION_REJECTED", {"id": hid, "reason": reason, "hypothesis": h})
            continue
        out.append({"id": hid, "kind": h["kind"], "params": h.get("params", {}),
                    "statement": h.get("statement", ""), "source": "expert" if cite.startswith("expert:") else "grammar",
                    "cites": cite, "quote": h["quote"], "dissent": []})
    return out
