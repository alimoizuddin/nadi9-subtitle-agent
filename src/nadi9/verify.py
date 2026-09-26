"""The independent checker.

It never asks the model anything. It re-derives every claim in a proposal from the lexicon,
the tested rules and the episode metadata (who speaks to whom, their ages, the timecodes).
The model's own glosses and confidence are recorded but never used as evidence.
"""
from __future__ import annotations

import re

from . import guard
from .lexicon import trusted_phrases
from .morph import analyse, clean
from .prompts import relation
from .rules import ACTIVE, TRUSTED, rule_by_kind, suffix_table
from .util import IRREGULAR, NEGATORS, content_lemmas, lemma, meaning_phrases, tc_to_seconds, tokenize_en

PAST_FORMS = {w for w, l in IRREGULAR.items() if w not in ("is", "are", "am", "me", "us", "him", "her",
                                                            "your", "my", "his", "does", "says", "children")}
PRONOUNS = {"ma", "mani", "tu", "tuvan", "vo"}
VERB_FEATS = {"PAST", "FUT", "HORT", "RESP"}


class Result:
    def __init__(self):
        self.checks: list[dict] = []
        self.deps = {"terms": set(), "rules": set(), "evidence": set()}
        self.conflicts: list[str] = []

    def add(self, check, status, detail, refs=(), blocking=False, kind=None, penalty=0.0, **data):
        self.checks.append({"check": check, "status": status, "detail": detail, "refs": list(refs),
                            "blocking": blocking, "kind": kind or check, "penalty": penalty, "data": data})

    @property
    def fails(self):
        return [c for c in self.checks if c["status"] == "FAIL"]

    @property
    def blocking(self):
        return [c for c in self.checks if c["status"] == "WARN" and c["blocking"]]


def _phrase_words(phrases: set[str]) -> set[str]:
    return {w for p in phrases for w in p.split()}


def _src_lemmas(src) -> set[str]:
    out = set()
    for w in src or []:
        w = str(w).strip().lower()
        if w == "?":
            out.add("?")
            continue
        for t in tokenize_en(w):
            out.add("not" if t in NEGATORS else lemma(t))
    return out


def _source_tense(text: str) -> set[str]:
    words = tokenize_en(text)
    t = set()
    if "will" in words or "'ll" in words:
        t.add("FUT")
    if any(w in PAST_FORMS or (w.endswith("ed") and len(w) > 4) for w in words):
        t.add("PAST")
    return t


def verify(line: dict, chars: dict, proposal: dict, lex: dict, rules: list[dict], cfg: dict) -> Result:
    res = Result()
    speaker, addressee = chars[line["speaker"]], chars[line["addressee"]]
    rel = relation(speaker, addressee)
    source = line["text"]
    text = proposal.get("nadi_9_text")
    tokens = proposal.get("tokens") or []
    terms = {t for t, c in lex.items()}
    stab = suffix_table(rules)
    names = {c["name"].lower() for c in chars.values()}

    gaps = proposal.get("gaps") or []
    dropped = proposal.get("dropped") or []

    # dependencies on terms that could resolve a gap later (so a correction re-opens the line)
    for g in gaps:
        gl = {lemma(w) for w in tokenize_en(g.get("words", ""))}
        for term, c in lex.items():
            if any(_phrase_words(meaning_phrases(m)) & gl for s in c["senses"] for m in s["all_meanings"]):
                res.deps["terms"].add(term)

    _timing(line, text or "", res, cfg)

    if text is None:
        if not gaps:
            res.add("FORMAT", "FAIL", "no translation and no gap stated")
        else:
            res.add("EVIDENCE", "WARN", "translation withheld: " + "; ".join(g.get("words", "") for g in gaps),
                    blocking=True, kind="GAP")
        return res

    if guard.scan(text):
        res.add("INJECTION", "FAIL", "model output contains instruction-like text")

    words_in_text = [clean(w) for w in re.findall(r"[\w-]+", text)]
    if [clean(t["t"]) for t in tokens] != words_in_text:
        res.add("FORMAT", "FAIL", f"token list does not match text: {words_in_text}")

    src_all = {("not" if w in NEGATORS else lemma(w)) for w in tokenize_en(source)}
    if source.strip().endswith("?"):
        src_all.add("?")
    covered: set[str] = set()
    analyses = []

    for tok in tokens:
        t = clean(tok["t"])
        a = analyse(t, terms, stab)
        analyses.append(a)
        srcl = _src_lemmas(tok.get("src"))
        covered |= srcl
        stray = srcl - src_all
        if stray:
            res.add("ADDITION", "FAIL", f"'{t}' claims to translate {sorted(stray)}, which are not in the source")

        if a["kind"] == "number":
            if t not in re.findall(r"\d+", source):
                res.add("NUMBERS", "FAIL", f"number {t} not in source")
            continue
        if t in names:
            continue
        if a["kind"] == "unknown" or a["root"] is None:
            if lemma(t) in src_all and t.isascii():
                _loan(t, rules, res)
                continue
            res.add("VOCAB", "FAIL", f"'{t}' is not in any source", kind="UNSUPPORTED_TERM")
            continue
        if a["unknown_suffix"]:
            res.add("MORPH", "FAIL", f"'{t}' = {a['root']} + unknown suffix '-{a['unknown_suffix']}'",
                    kind="UNSUPPORTED_MORPHEME")
            continue

        claim = lex[a["root"]]
        res.deps["terms"].add(a["root"])
        res.deps["evidence"].update(claim.get("evidence", []))
        st = claim["status"]
        if st == "UNSUPPORTED":
            res.add("VOCAB", "FAIL", f"'{a['root']}': every meaning is poisoned or superseded", kind="POISON_USE")
        elif st == "CONTESTED":
            rivals = " | ".join(f"'{r['meaning']}' ({', '.join(r['refs'])})" for r in claim.get("rivals", []))
            detail = f"'{a['root']}': '{claim['meaning']}' ({', '.join(claim['evidence'])}) vs {rivals}"
            res.add("VOCAB", "WARN", detail, refs=claim["evidence"], blocking=True, kind="CONTESTED", penalty=0.3,
                    term=a["root"], meaning=claim["meaning"], evidence=claim["evidence"], rivals=claim.get("rivals", []))
            res.conflicts.append(detail)
        elif st == "WEAK":
            res.add("VOCAB", "WARN", f"'{a['root']}' = '{claim['meaning']}' rests on {', '.join(claim['evidence'])} only",
                    refs=claim["evidence"], blocking=True, kind="WEAK_TERM", penalty=0.2,
                    term=a["root"], meaning=claim["meaning"], evidence=claim["evidence"])
        elif st == "SUPPORTED":
            res.add("VOCAB", "PASS", f"'{a['root']}' supported by {', '.join(claim['evidence'])}", penalty=0.04)
        else:
            res.add("VOCAB", "PASS", f"'{a['root']}' confirmed by {', '.join(claim['evidence'])}")

        for suf, feat in zip(a["suffixes"], a["feats"]):
            r = next((r for r in rules if r["status"] in ACTIVE and r["params"].get("suffix") == suf), None)
            if not r:
                continue
            res.deps["rules"].add(r["id"])
            if r["status"] == "SINGLE_SOURCE":
                res.add("MORPH", "WARN", f"'-{suf}' ({feat}) rests on {r['cites']} and {', '.join(r['attested']) or 'no speech'}",
                        refs=[r["cites"], *r["attested"]], blocking=True, kind="SINGLE_SOURCE_MORPHEME", penalty=0.25,
                        token=t, suffix=suf, feature=feat, sources=[r["cites"], *r["attested"]])
            elif r["status"] not in TRUSTED:
                res.add("MORPH", "WARN", f"'-{suf}' rule {r['id']} is {r['status']}", penalty=0.08)

        _meaning(tok, t, a, claim, srcl, res)
        _sensitivity(claim, rel, speaker, addressee, line, res)

    for d in dropped:
        covered |= {lemma(w) for w in tokenize_en(d.get("words", ""))}
        res.add("COVERAGE", "WARN", f"dropped '{d.get('words')}': {d.get('reason', '')}", blocking=True,
                kind="DROPPED", penalty=0.1, words=d.get("words"), reason=d.get("reason", ""))
    for g in gaps:
        covered |= {lemma(w) for w in tokenize_en(g.get("words", ""))}
        res.add("COVERAGE", "WARN", f"partial: no evidence for '{g.get('words')}'", blocking=True, kind="PARTIAL_GAP",
                penalty=0.3, words=g.get("words"), reason=g.get("reason", ""))

    need = {w for w in content_lemmas(source) if w not in names and not w.isdigit()}
    missing = need - covered
    if missing:
        res.add("COVERAGE", "FAIL", f"source meaning not translated: {sorted(missing)}", kind="OMISSION")

    for n in {c["name"] for c in chars.values()}:
        if re.search(rf"\b{n}\b", source) and n.lower() not in {w.lower() for w in words_in_text}:
            res.add("NAMES", "FAIL", f"name {n} missing")

    _grammar(line, source, tokens, analyses, text, lex, rules, rel, res)
    return res


def _loan(t, rules, res):
    r = rule_by_kind(rules, "loan_unchanged")
    if not r or r["status"] not in ACTIVE:
        res.add("LOAN", "FAIL", f"'{t}' is English and no active loan rule allows it", kind="UNSUPPORTED_TERM")
        return
    res.deps["rules"].add(r["id"])
    if r.get("dissent"):
        detail = f"loan '{t}' kept unchanged per {r['id']}; dissent: {', '.join(r['dissent'])}"
        res.add("LOAN", "WARN", detail, refs=[r["id"], *r["dissent"]], blocking=True, kind="LOAN_DISSENT", penalty=0.15,
                loan=t, rule=r["id"], dissent=r["dissent"])
        res.conflicts.append(f"grammar:{r['id']} vs {', '.join(r['dissent'])}")
    else:
        res.add("LOAN", "PASS", f"loan '{t}' per {r['id']}")


def _meaning(tok, t, a, claim, srcl, res):
    if not srcl:
        if claim.get("pos") in ("PART", "POST") or a["root"] in ("ka",):
            return
        res.add("ADDITION", "FAIL", f"'{t}' translates nothing in the source", kind="ADDITION")
        return
    ok_words = _phrase_words(trusted_phrases(claim)) | ({"?"} if "question particle" in trusted_phrases(claim) else set())
    if srcl & ok_words:
        return
    for s in claim["senses"]:
        if s["status"] in ("POISON_SUSPECT", "SUPERSEDED") and srcl & _phrase_words(meaning_phrases(s["meaning"])):
            res.add("MEANING", "FAIL", f"'{a['root']}' used as '{s['meaning']}', a {s['status']} meaning", kind="POISON_USE")
            return
    res.add("MEANING", "FAIL", f"'{a['root']}' means '{claim['meaning']}', not {sorted(srcl)}", kind="MEANING_MISMATCH")


def _sensitivity(claim, rel, speaker, addressee, line, res):
    for f in claim["flags"]:
        if f["flag"] != "STATUS_SENSITIVE":
            continue
        if rel == "elder":
            detail = (f"'{claim['term']}' said by {speaker['name']} ({speaker['age']}) to {addressee['name']} "
                      f"({addressee['age']}): flagged by {', '.join(f['refs'])}")
            if f["dissent"]:
                detail += f"; dissent {', '.join(f['dissent'])}"
                res.conflicts.append(f"{', '.join(f['refs'])} vs {', '.join(f['dissent'])}")
            res.add("RESPECT", "WARN", detail, refs=f["refs"] + f["dissent"], blocking=True, kind="RESPECT_RISK", penalty=0.3,
                    term=claim["term"], against=f["refs"], dissent=f["dissent"])
        else:
            res.add("RESPECT", "PASS", f"'{claim['term']}' used between {rel}s; sensitivity applies upward only")


def _is_verb(a, lex):
    return bool(set(a["feats"]) & VERB_FEATS) or (a["root"] in lex and lex[a["root"]].get("pos") == "V")


def _grammar(line, source, tokens, analyses, text, lex, rules, rel, res):
    toks = [clean(t["t"]) for t in tokens]

    q = rule_by_kind(rules, "question_final")
    if q and q["status"] in ACTIVE:
        res.deps["rules"].add(q["id"])
        is_q = source.strip().endswith("?")
        last = toks[-1] if toks else ""
        if is_q and last != q["params"]["particle"]:
            res.add("GRAMMAR", "FAIL", f"question without final '{q['params']['particle']}' ({q['id']})", kind="GRAMMAR")
        elif not is_q and last == q["params"]["particle"]:
            res.add("GRAMMAR", "FAIL", f"'{last}' on a non-question ({q['id']})", kind="GRAMMAR")

    neg = rule_by_kind(rules, "neg_before_verb")
    if neg and neg["status"] in ACTIVE:
        res.deps["rules"].add(neg["id"])
        p = neg["params"]["particle"]
        has_neg_src = any(w in NEGATORS for w in tokenize_en(source))
        if has_neg_src and p not in toks:
            res.add("GRAMMAR", "FAIL", f"source is negative but '{p}' is missing ({neg['id']})", kind="OMISSION")
        if p in toks:
            i = toks.index(p)
            if i + 1 >= len(toks) or not _is_verb(analyses[i + 1], lex):
                res.add("GRAMMAR", "FAIL", f"'{p}' not directly before a verb ({neg['id']})", kind="GRAMMAR")
            if not has_neg_src:
                res.add("GRAMMAR", "FAIL", f"'{p}' adds a negation the source does not have", kind="ADDITION")

    want = _source_tense(source)
    have = {f for a in analyses for f in a["feats"] if f in ("PAST", "FUT")}
    for tense in ("PAST", "FUT"):
        r = next((r for r in rules if r["kind"] == "tense_suffix" and r["params"].get("feature") == tense
                  and r["status"] in ACTIVE), None)
        if not r:
            continue
        if tense in want and tense not in have and any(_is_verb(a, lex) for a in analyses):
            res.add("GRAMMAR", "FAIL", f"source is {tense} but no verb carries -{r['params']['suffix']} ({r['id']})", kind="GRAMMAR")
            res.deps["rules"].add(r["id"])
        if tense in have:
            res.deps["rules"].add(r["id"])
            if tense not in want:
                res.add("GRAMMAR", "FAIL", f"verb marked {tense} but source is not ({r['id']})", kind="GRAMMAR")

    vf = rule_by_kind(rules, "verb_final")
    clauses = _clauses(text, toks, analyses)
    if vf and vf["status"] in ACTIVE:
        res.deps["rules"].add(vf["id"])
        for cl in clauses:
            core = [(t, a) for t, a in cl if t != (q["params"]["particle"] if q else "ka")]
            if any(_is_verb(a, lex) for _, a in core) and not _is_verb(core[-1][1], lex):
                res.add("GRAMMAR", "FAIL", f"verb not final in '{' '.join(t for t, _ in cl)}' ({vf['id']})", kind="GRAMMAR")

    rp = rule_by_kind(rules, "resp_pronoun")
    if rp and rp["status"] in ACTIVE:
        res.deps["rules"].add(rp["id"])
        if rp["params"]["elder"] in toks and rel != "elder":
            res.add("RESPECT", "FAIL", f"'{rp['params']['elder']}' to a {rel} ({rp['id']})", kind="RESPECT")
        if rp["params"]["other"] in toks and rel == "elder":
            res.add("RESPECT", "FAIL", f"'{rp['params']['other']}' to an elder is rude ({rp['id']})", kind="RESPECT")

    rs = rule_by_kind(rules, "resp_suffix")
    if rs and rs["status"] in ACTIVE:
        res.deps["rules"].add(rs["id"])
        elder_pron = rp["params"]["elder"] if rp else "tuvan"
        for cl in clauses:
            subj = next((t for t, _ in cl if t in PRONOUNS), None)
            verbs = [(t, a) for t, a in cl if _is_verb(a, lex)]
            if not subj or not verbs:
                continue
            t, a = verbs[-1]
            if subj == elder_pron and "RESP" not in a["feats"]:
                res.add("RESPECT", "FAIL", f"'{t}' has a respected subject but no -{rs['params']['suffix']} ({rs['id']})", kind="RESPECT")
            if subj in ("ma", "mani", "tu") and "RESP" in a["feats"]:
                res.add("RESPECT", "FAIL", f"'{t}' takes -{rs['params']['suffix']} but its subject is '{subj}' ({rs['id']})", kind="RESPECT")


def _clauses(text, toks, analyses):
    """Split at sentence punctuation in the text (commas after a vocative stay in the clause)."""
    ends, count = [], 0
    for piece in re.split(r"(?<=[.!?])\s+", text.strip()):
        count += len(re.findall(r"[\w-]+", piece))
        ends.append(count)
    out, start = [], 0
    for e in ends:
        if e > start:
            out.append(list(zip(toks[start:e], analyses[start:e])))
        start = e
    return out


def _timing(line, text, res, cfg):
    dur = tc_to_seconds(line["end"]) - tc_to_seconds(line["start"])
    shown = text or line["text"]
    if dur < cfg["min_duration"]:
        res.add("TIMING", "WARN", f"on screen {dur:.1f}s (minimum {cfg['min_duration']}s)", blocking=True, kind="TIMING", penalty=0.05)
    cps = len(shown) / dur if dur > 0 else 99
    if cps > cfg["max_cps"]:
        res.add("TIMING", "WARN", f"{cps:.1f} chars/sec (limit {cfg['max_cps']})", blocking=True, kind="TIMING", penalty=0.05)
    if len(shown) > 2 * cfg["max_line_chars"]:
        res.add("TIMING", "WARN", f"{len(shown)} chars will not fit two lines", blocking=True, kind="TIMING")
