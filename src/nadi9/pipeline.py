"""The agent loop: inspect -> learn -> test -> plan -> translate -> verify -> repair -> decide,
with surprise events handled by tracing what they touch and re-running only that."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from . import decide as decide_mod
from . import guard, lexicon, prompts, rules as rules_mod, sources
from .llm import Budget, BudgetExceeded, FlakyProvider, ModelUnavailable
from .pack import load_pack
from .util import extract_json, lemma, meaning_words, tc_to_seconds, tokenize_en
from .verify import verify

DEFAULT_CFG = {"max_model_calls": 25, "max_tool_calls": 50, "max_cps": 17.0, "min_duration": 1.0,
               "max_line_chars": 42}

FIXABLE = {"GRAMMAR", "RESPECT", "MEANING_MISMATCH", "UNSUPPORTED_TERM", "UNSUPPORTED_MORPHEME", "POISON_USE",
           "OMISSION", "ADDITION", "FORMAT", "NUMBERS", "NAMES", "INJECTION"}


class ToolFailure(Exception):
    pass


def transcribe(audio_path: Path) -> list[dict]:
    """Transcription tool. The synthetic pack ships no audio, so this fails for real."""
    if not audio_path.exists():
        raise ToolFailure(f"audio file not found: {audio_path.name}")
    raise ToolFailure("no speech-to-text backend configured")


class Agent:
    def __init__(self, pack_dir, provider, events=None, cfg=None):
        self.cfg = {**DEFAULT_CFG, **(cfg or {})}
        self.pack_dir = Path(pack_dir)
        self.provider = provider if isinstance(provider, FlakyProvider) else FlakyProvider(provider)
        self.events = list(events or [])
        self.budget = Budget(self.cfg["max_model_calls"], self.cfg["max_tool_calls"])
        self.kv = 0
        self.log_rows: list[dict] = []
        self.security: list[dict] = []
        self.tool_failures: list[dict] = []
        self.retracted: set[str] = set()
        self.corrections: list[dict] = []
        self.rules: list[dict] = []
        self.grammar_items: list[dict] = []
        self.expert_positions: list[dict] = []
        self.suspects: dict = {}
        self.lex: dict = {}
        self.agreement: dict = {}
        self.proposals: dict = {}
        self.decisions: dict = {}
        self.history: dict = {}
        self.replans: list[dict] = []
        self.plan: list[dict] = []

    # --- plumbing -------------------------------------------------------------------------

    def log(self, kind, detail):
        self.log_rows.append({"t": dt.datetime.now().isoformat(timespec="seconds"), "kv": self.kv,
                              "kind": kind, "detail": detail})

    def call_model(self, key: str, prompt: str):
        for attempt in (1, 2):
            try:
                self.budget.model()
            except BudgetExceeded as e:
                self.log("BUDGET_EXHAUSTED", {"key": key, "reason": str(e)})
                return None
            try:
                text = self.provider.complete(key, prompt)
                self.log("MODEL_CALL", {"key": key, "attempt": attempt, "ok": True, "prompt_chars": len(prompt)})
                return text
            except ModelUnavailable as e:
                self.log("MODEL_UNAVAILABLE", {"key": key, "attempt": attempt, "reason": str(e)})
        self.log("MODEL_GAVE_UP", {"key": key, "action": "lines left undrafted and sent to review"})
        return None

    def tool(self, name, detail=None):
        try:
            self.budget.tool()
        except BudgetExceeded as e:
            self.log("BUDGET_EXHAUSTED", {"tool": name, "reason": str(e)})
            return False
        self.log("TOOL_CALL", {"tool": name, **(detail or {})})
        return True

    def fire(self, at: str):
        for ev in [e for e in self.events if e.get("at") == at]:
            self.events.remove(ev)
            getattr(self, f"_ev_{ev['type']}")(ev)

    # --- run ------------------------------------------------------------------------------

    def run(self):
        self.pack = load_pack(self.pack_dir)
        self.chars = self.pack.characters
        self.log("PACK_LOADED", {"files": self.pack.files_read, "synthetic": self.pack.manifest.get("synthetic")})
        guard.sanitize_pack(self.pack, self.security)
        for s in self.security:
            self.log("SECURITY_QUARANTINE", s)
        self.fire("start")
        self._inspect_interviews()
        self._learn()
        self.fire("after_learning")
        self._make_plan()
        for i, step in enumerate(self.plan, 1):
            self.fire(f"before_step:{i}")
            self.fire(f"before_scene:{step['scene']}")
            self._translate_scene(step["scene"])
            self.fire(f"after_scene:{step['scene']}")
            self.fire(f"after_step:{i}")
        for ev in list(self.events):
            self.log("EVENT_NOT_TRIGGERED", ev)
        return self

    def _inspect_interviews(self):
        for iv in self.pack.interviews:
            if iv.get("transcript"):
                continue
            if not self.tool("transcribe", {"interview": iv["id"]}):
                continue
            try:
                iv["transcript"] = transcribe(self.pack_dir / "interviews" / iv["audio"])
            except ToolFailure as e:
                gap = {"tool": "transcribe", "target": iv["id"], "topic": iv.get("topic"), "error": str(e),
                       "impact": f"evidence on '{iv.get('topic')}' from {iv['id']} is unavailable; related decisions lean on other sources"}
                self.tool_failures.append(gap)
                self.log("TOOL_FAILURE", gap)

    # --- learning -------------------------------------------------------------------------

    def _learn(self):
        text = self.call_model("rules_extract", prompts.rules_extract(self.pack.grammar_text, self.pack.experts))
        if text is None:
            self.log("NO_RULES", "rule extraction unavailable; every line will need review")
            raw = {"hypotheses": [], "lexical_items": [], "expert_positions": []}
        else:
            raw = extract_json(text)
        srcs = {"grammar": self.pack.grammar_text, **{f"expert:{n['id']}": n["text"] for n in self.pack.experts}}
        self.rules = rules_mod.normalise_hypotheses(raw.get("hypotheses", []), srcs, self.log)
        self.grammar_items = []
        for gi in raw.get("lexical_items", []):
            if rules_mod.quote_ok(gi.get("quote", ""), self.pack.grammar_text) and gi.get("term", "") in gi["quote"]:
                self.grammar_items.append(gi)
            else:
                self.log("LEXICAL_ITEM_REJECTED", {"item": gi, "reason": "quote not verbatim in grammar note"})
        note_ids = {n["id"] for n in self.pack.experts}
        rule_ids = {r["id"] for r in self.rules}
        for p in raw.get("expert_positions", []):
            if p.get("note") in note_ids and p.get("rule") in rule_ids:
                self.expert_positions.append(p)
                if p.get("stance") == "dissents":
                    next(r for r in self.rules if r["id"] == p["rule"])["dissent"].append(f"expert:{p['note']}")
        self._retest("initial learning")

    def _retest(self, why):
        dict_terms = {e["term"] for e in self.pack.dict_a + self.pack.dict_b}
        for r in self.rules:
            rules_mod.test_rule(r, self.pack.examples, self.retracted, self.pack.interviews, dict_terms)
        self.suspects = rules_mod.suspect_examples(self.rules)
        excluded = self.retracted | set(self.suspects)
        stab = rules_mod.suffix_table(self.rules)
        self.agreement = sources.dictionary_agreement(self.pack, stab, excluded)
        weights = {k: v["agreement"] or 0.0 for k, v in self.agreement.items()}
        self.lex = lexicon.build(self.pack, stab, excluded, weights, self.grammar_items, self.corrections)
        self.kv += 1
        self.log("KNOWLEDGE_UPDATED", {
            "why": why, "rules": {r["id"]: r["status"] for r in self.rules},
            "suspect_examples": self.suspects, "retracted": sorted(self.retracted),
            "poisoned": [f"{t}:{s['meaning']}" for t, c in self.lex.items() for s in c["senses"] if s["status"] == "POISON_SUSPECT"],
            "contested": [t for t, c in self.lex.items() if c["status"] == "CONTESTED"],
            "dict_agreement": weights})

    # --- planning -------------------------------------------------------------------------

    def _make_plan(self):
        index: dict[str, set[str]] = {}
        for term, c in self.lex.items():
            if c["status"] in ("CONFIRMED", "SUPPORTED"):
                for w in meaning_words(c["meaning"] or ""):
                    index.setdefault(w, set()).add(term)
        sensitive = {t for t, c in self.lex.items() if c["flags"]}
        sens_words = {w for t in sensitive for w in meaning_words(self.lex[t]["meaning"] or "")}
        scenes = {}
        for ln in self.pack.episode["lines"]:
            s, a = self.chars[ln["speaker"]], self.chars[ln["addressee"]]
            rel = prompts.relation(s, a)
            words = [lemma(w) for w in tokenize_en(ln["text"])]
            reasons = []
            unknown = [w for w in words if w not in index and len(w) > 2 and w not in ("the", "and", "will", "not", "did")]
            if unknown:
                reasons.append(f"{len(unknown)} words without solid evidence")
            if rel == "elder":
                reasons.append("addressed upward (respect forms)")
            if rel == "elder" and set(words) & sens_words:
                reasons.append("status-sensitive word toward an elder")
            if tc_to_seconds(ln["end"]) - tc_to_seconds(ln["start"]) < self.cfg["min_duration"]:
                reasons.append("very short on screen")
            score = 2 * len(unknown) + (1 if rel == "elder" else 0) + (4 if "status-sensitive word toward an elder" in reasons else 0) \
                + (2 if "very short on screen" in reasons else 0)
            sc = scenes.setdefault(ln["scene"], {"scene": ln["scene"], "risk": 0, "lines": []})
            sc["risk"] += score
            sc["lines"].append({"id": ln["id"], "risk": score, "reasons": reasons})
        self.plan = sorted(scenes.values(), key=lambda s: -s["risk"])
        reserve = max(0, self.cfg["max_model_calls"] - 1 - 2 * len(self.plan))
        self.log("PLAN", {"order": [s["scene"] for s in self.plan],
                          "risk": {s["scene"]: s["risk"] for s in self.plan},
                          "model_calls": {"learning": 1, "draft+repair per scene": 2, "reserve for corrections": reserve},
                          "riskiest_lines": sorted((l for s in self.plan for l in s["lines"]), key=lambda l: -l["risk"])[:5]})

    # --- translation ----------------------------------------------------------------------

    def _lines(self, ids=None, scene=None):
        return [l for l in self.pack.episode["lines"] if (ids is None or l["id"] in ids) and (scene is None or l["scene"] == scene)]

    def _translate_scene(self, scene):
        lines = self._lines(scene=scene)
        self._draft(lines, key=f"translate_{scene}", repair_key=f"repair_{scene}")

    def _draft(self, lines, key, repair_key, why="draft"):
        if not lines:
            return
        self.tool("retrieve_evidence", {"for": key, "lines": [l["id"] for l in lines]})
        setting = self.pack.episode.get("setting", "")
        text = self.call_model(key, prompts.translate(lines, self.chars, self.lex, self.rules, setting))
        props = self._parse(text, lines)
        for l in lines:  # an outage must never wipe an earlier draft
            if props[l["id"]].get("_missing") and l["id"] in self.proposals:
                props[l["id"]] = self.proposals[l["id"]]
        results = {l["id"]: self._verify(l, props[l["id"]]) for l in lines}

        broken = [l for l in lines if props[l["id"]].get("nadi_9_text") is not None
                  and any(c["kind"] in FIXABLE for c in results[l["id"]].fails)]
        if broken:
            failures = {l["id"]: [c["detail"] for c in results[l["id"]].fails] for l in broken}
            self.log("REPAIR_REQUESTED", {"key": repair_key, "failures": failures})
            prev = {l["id"]: props[l["id"]] for l in broken}
            text = self.call_model(repair_key, prompts.repair(broken, self.chars, self.lex, self.rules, setting, prev, failures))
            if text is not None:
                fixed = self._parse(text, broken)
                for l in broken:
                    if fixed[l["id"]].get("_missing"):
                        continue
                    self.history.setdefault(l["id"], []).append({"stage": "rejected_draft", "proposal": props[l["id"]],
                                                                  "failures": failures[l["id"]], "kv": self.kv})
                    props[l["id"]] = fixed[l["id"]]
                    results[l["id"]] = self._verify(l, fixed[l["id"]])
        for l in lines:
            self._record(l, props[l["id"]], results[l["id"]], why)

    def _parse(self, text, lines):
        out = {l["id"]: {"subtitle_id": l["id"], "nadi_9_text": None, "tokens": [], "_missing": True,
                         "gaps": [{"words": l["text"], "reason": "model unavailable; not drafted"}]} for l in lines}
        if text is None:
            return out
        try:
            data = extract_json(text)
        except ValueError as e:
            self.log("MODEL_OUTPUT_UNPARSEABLE", {"error": str(e)})
            return out
        for row in data.get("lines", []):
            if row.get("subtitle_id") in out:
                out[row["subtitle_id"]] = row
        return out

    def _verify(self, line, proposal):
        self.tool("validate", {"line": line["id"]})
        return verify(line, self.chars, proposal, self.lex, self.rules, self.cfg)

    def _record(self, line, proposal, res, why):
        d = decide_mod.decide(line, self.chars, proposal, res, self.pack.episode.get("setting", ""))
        s, a = self.chars[line["speaker"]], self.chars[line["addressee"]]
        evidence = sorted(res.deps["evidence"]) + sorted(f"rule:{r}" for r in res.deps["rules"])
        rec = {
            "subtitle_id": line["id"], "scene": line["scene"], "start": line["start"], "end": line["end"],
            "speaker": s["name"], "addressee": a["name"], "relation": prompts.relation(s, a),
            "source_text": line["text"], "nadi_9_text": proposal.get("nadi_9_text"),
            "gloss": [f"{t.get('t')}={t.get('gloss')}" for t in proposal.get("tokens") or []],
            "confidence": d["confidence"], "confidence_reason": d["confidence_reason"], "decision": d["decision"],
            "evidence": evidence, "assumptions": proposal.get("assumptions", []),
            "conflicts": sorted(set(res.conflicts)), "review_question": d["review_question"],
            "other_questions": d["other_questions"], "review_priority": d["priority"],
            "checks": [{k: c[k] for k in ("check", "status", "detail")} for c in res.checks if c["status"] != "PASS"],
            "model_self_confidence": proposal.get("self_confidence"),
            "knowledge_version": self.kv, "why": why,
            "deps": {k: sorted(v) for k, v in res.deps.items()},
        }
        if line["id"] in self.decisions:
            self.history.setdefault(line["id"], []).append({"stage": "superseded_decision", **self.decisions[line["id"]]})
        self.decisions[line["id"]] = rec
        self.proposals[line["id"]] = proposal
        self.log("DECISION", {k: rec[k] for k in ("subtitle_id", "decision", "confidence", "nadi_9_text", "why")})

    # --- surprise events ------------------------------------------------------------------

    def _affected(self, terms=(), rules=(), evidence=()):
        out = []
        for lid, d in self.decisions.items():
            if set(d["deps"]["terms"]) & set(terms) or set(d["deps"]["rules"]) & set(rules) \
                    or set(d["deps"]["evidence"]) & set(evidence):
                out.append(lid)
        return sorted(out)

    def _reverify(self, ids, event_id, redraft_if_open=False):
        before = {i: (self.decisions[i]["decision"], self.decisions[i]["nadi_9_text"], self.decisions[i]["confidence"]) for i in ids}
        q_before = {i: self.decisions[i]["review_question"] for i in ids}
        redraft = []
        for lid in ids:
            line = self._lines(ids={lid})[0]
            res = self._verify(line, self.proposals[lid])
            self._record(line, self.proposals[lid], res, f"re-checked after {event_id}")
            if redraft_if_open and self.decisions[lid]["decision"] != "ACCEPT":
                redraft.append(line)
        if redraft:
            self._draft(redraft, key=f"redraft_{event_id}", repair_key=f"repair_{event_id}", why=f"redrafted after {event_id}")
        changes = []
        for i in ids:
            after = (self.decisions[i]["decision"], self.decisions[i]["nadi_9_text"], self.decisions[i]["confidence"])
            q_after = self.decisions[i]["review_question"]
            changes.append({"line": i, "before": before[i], "after": after, "changed": before[i] != after,
                            "redrafted": any(l["id"] == i for l in redraft),
                            "question_before": q_before[i], "question_after": q_after,
                            "question_changed": q_before[i] != q_after})
        untouched = sorted(set(self.decisions) - set(ids))
        rep = {"event": event_id, "kv": self.kv, "affected": ids, "untouched": untouched, "changes": changes}
        self.replans.append(rep)
        self.log("REPLAN", rep)

    def _ev_model_failure(self, ev):
        self.provider.fail_next += ev.get("times", 1)
        self.log("EVENT", {"id": ev["id"], "type": "model_failure", "times": ev.get("times", 1)})

    def _ev_model_rule_proposal(self, ev):
        r = {**ev["rule"], "source": "model", "cites": "model", "quote": "", "dissent": []}
        dict_terms = {e["term"] for e in self.pack.dict_a + self.pack.dict_b}
        rules_mod.test_rule(r, self.pack.examples, self.retracted | set(self.suspects), self.pack.interviews, dict_terms)
        self.log("EVENT", {"id": ev["id"], "type": "model_rule_proposal", "rule": r["id"], "statement": r.get("statement"),
                           "model_confidence": ev.get("claimed_confidence"), "support": r["support"],
                           "counter": r["counter"], "attested": r["attested"], "verdict": r["status"]})
        if r["status"] == "REJECTED_UNSUPPORTED":
            self.rejected_rules = getattr(self, "rejected_rules", []) + [r]
            return
        self.rules.append(r)
        self._retest(f"{ev['id']}: model rule accepted")

    def _ev_linguist_correction(self, ev):
        terms = []
        for ch in ev["changes"]:
            if ch["op"] == "set_meaning":
                self.corrections.append({"term": ch["term"], "meaning": ch["meaning"], "event": ev["id"], "from": ev.get("from")})
                terms.append(ch["term"])
        old = {t: (self.lex.get(t) or {}).get("status") for t in terms}
        self.log("EVENT", {"id": ev["id"], "type": "linguist_correction", "from": ev.get("from"), "changes": ev["changes"]})
        self._retest(f"{ev['id']}: correction from {ev.get('from')}")
        self.log("CLAIMS_CHANGED", {t: {"before": old[t], "after": self.lex[t]["status"], "meaning": self.lex[t]["meaning"]} for t in terms})
        self._reverify(self._affected(terms=terms), ev["id"], redraft_if_open=True)

    def _ev_example_retraction(self, ev):
        before = {r["id"]: r["status"] for r in self.rules}
        self.suspects_before_retraction = dict(self.suspects)
        self.retracted |= set(ev["examples"])
        self.log("EVENT", {"id": ev["id"], "type": "example_retraction", "examples": ev["examples"], "reason": ev.get("reason")})
        self._retest(f"{ev['id']}: examples retracted")
        # Only a change that can alter a check outcome matters: crossing into/out of ACTIVE or TRUSTED.
        def band(st):
            return (st in rules_mod.ACTIVE, st in rules_mod.TRUSTED)
        changed_rules = [r["id"] for r in self.rules if band(before.get(r["id"])) != band(r["status"])]
        quiet = [r["id"] for r in self.rules if before.get(r["id"]) != r["status"] and r["id"] not in changed_rules]
        if quiet:
            self.log("RULES_STRENGTHENED", {"rules": quiet, "note": "status changed within the same trust band; no check outcome can change"})
        already = [e for e in ev["examples"] if e in self.suspects_before_retraction]
        if already:
            self.log("RETRACTION_ALREADY_HANDLED", {"examples": already, "note": "already excluded as suspect; no decision cited them"})
        ids = self._affected(rules=changed_rules, evidence=[f"example:{e}" for e in ev["examples"]])
        self.log("RULES_CHANGED", {r: {"before": before[r], "after": next(x["status"] for x in self.rules if x["id"] == r)} for r in changed_rules})
        self._reverify(ids, ev["id"])
