# Architecture

## 1. The idea in one paragraph

The model is a **proposer**, never a source. It reads the evidence and proposes rule hypotheses and
subtitle drafts in a structured form. Deterministic code then tests every hypothesis against the
approved examples and checks every draft against the lexicon, the tested rules and the episode
metadata (who speaks to whom, their ages, the timecodes). A line is accepted only when every token,
suffix and rule it relies on is backed by independent sources. Otherwise the agent says exactly what
is missing and asks one question an expert can answer.

```
pack ──► guard ──► inspect sources ──► LEARN ─────────────► PLAN ──► per scene:  DRAFT ──► VERIFY ──► REPAIR ──► DECIDE
         (quarantine   (transcribe;     model extracts        risk-      (model)     (code)     (model,     (code)
          injections)   tool failure    hypotheses → code     ordered                            once)
                        recorded)       tests them → suspect                                            │
                                        examples → lexicon                                              ▼
                                        with measured trust                               decisions + dependency index
                                                ▲                                                       │
                              surprise event ───┴──── re-learn only what changed ◄── affected lines ◄───┘
```

## 2. Evidence pack schema

`pack/manifest.json` lists every source with type, author, date and scope. The loader reads only
files the manifest names, refuses paths that leave the pack root or start with `_`, and records
every file it opened (`pack.files_read`). Examples carry an interlinear gloss (`return-PAST-RESP`),
part of speech, the addressee's status and, for verbs, whether the subject outranks the speaker.
Adapting to STAGE's real pack means writing a loader to this shape; nothing downstream changes.

## 3. Planning

- **Learning first, once.** One model call extracts rule hypotheses and stated word meanings from
  the grammar note and expert notes. Each must quote its source verbatim; the quote is checked in
  code, so an invented rule or meaning is rejected before it is tested (`RULE_EXTRACTION_REJECTED`).
- **Risk-ordered scenes.** Each line is scored for words without solid evidence, upward address
  (respect forms), status-sensitive words toward an elder and very short timing. Scenes run riskiest
  first, so if the budget runs out, the easy lines are the ones left undone, not the dangerous ones.
- **Budget plan.** 1 learning call + at most 2 calls per scene (draft, one repair) + a reserve for
  corrections. The sample run uses 7 of 25 model calls and 26 of 50 tool calls.

## 4. Memory (structured state, not chat history)

| Store | Holds |
|---|---|
| `rules` | Hypothesis, kind, params, source quote, supporting and counter examples, interview attestations, expert dissent, status |
| `lexicon` | Per term: every candidate meaning, clustered; per cluster the source families and refs behind it; status; flags such as `STATUS_SENSITIVE` with who says so and who disagrees |
| `suspects` / `retracted` | Approved examples doubted by the evidence, and those withdrawn by the team |
| `decisions` | Per line, the decision plus `deps` (terms, rules, evidence ids it used) and the knowledge version it was made under |
| `history` / `revisions.json` | Every rejected draft and superseded decision, so an evaluator can see what the agent knew at each step |

## 5. Source trust

Trust is **measured**, not assumed from size or date:

- Each dictionary is scored by how often its entries agree with the approved examples. In the
  sample: Dictionary A 85% (27 checked), Dictionary B 100% (16 checked). A's family weight is
  `0.5 × 0.85`, B's `0.85 × 1.0`.
- Meanings are clustered per word, and a cluster's strength is the sum over **independent source
  families** (example, dictB, correction, expert, grammar, interview, dictA). Ten Dictionary A
  entries still count as one family.
- A Dictionary A meaning contradicted by ≥2 approved examples *and* Dictionary B or an expert is
  **poisoned** and excluded (anno, hesu, mo in the sample). A meaning contradicted by only one example
  stays **contested** (tamba), because one example may itself be wrong. Two of them were.
- An approved example that breaks a rule with ≥3 supporting examples becomes **suspect** (the example
  is doubted, not the rule) and is excluded from evidence (E07, E15).
- Viewer feedback is never evidence for a word. It can raise the priority of a review.
- Expert notes add caution and never remove it: a dissent turns a rule into a blocking review point.
- Model output is never evidence.

## 6. Verification (independent of the model)

`verify.py` never calls the model. For each draft it checks:

| Check | Rejects |
|---|---|
| Vocabulary | words in no source; poisoned or superseded meanings; unknown suffixes (morphology is parsed with the *currently accepted* suffix rules, so a rejected `-lu` cannot parse) |
| Meaning | a token's claimed source words must match one of the word's trusted meanings, compared as whole phrases |
| Coverage | source content words not translated; words claimed that are not in the source |
| Numbers, names | changed or missing |
| Grammar | negation position, verb-final clauses, tense suffix vs source tense, question particle |
| Respect | `tu`/`tuvan` against the speaker/addressee ages; `-ji` against the clause subject; status-sensitive words used upward |
| Timing | < 1.0 s on screen, > 17 chars/sec, more than two lines |
| Injection | instruction-like text in the model's output |

**Keeping the verifier from repeating the translator's mistake:** the verifier uses different
inputs from the translator (trusted lexicon status, rule test results, character ages, timecodes),
not the model's gloss or confidence. The model's `self_confidence` is recorded and reported
(`model_overconfident_on`) but never used. A test proves that changing it from 0.01 to 0.99 does
not change any decision.

**Confidence** starts at 0.95 and is reduced by named penalties (weak term −0.20, contested term −0.30,
single-source suffix −0.25, loan dissent −0.15, dropped words −0.10, timing −0.05). Any failed check
caps it at 0.30. The reason string lists the penalties that applied. `ACCEPT` requires ≥ 0.80 and no
blocking warning.

## 7. Failure recovery

| Failure | Behaviour |
|---|---|
| Model outage | one retry; then the lines are left undrafted and sent to review. An outage during a redraft keeps the previous draft. |
| Budget exhausted | remaining calls refused, lines abstain, logged `BUDGET_EXHAUSTED` |
| Unparseable model output | treated as an outage for those lines |
| Transcription tool fails | recorded as a gap with its impact; other sources carry the decision |
| Checker rejects a draft | one repair call carrying the exact failures; if the model cannot fix it with evidence, the meaning moves to `gaps` |
| Replay drift (prompt changed since recording) | logged `REPLAY_PROMPT_DRIFT` |

## 8. Change handling

Every decision stores the terms, rules and evidence ids it depended on. When an event arrives:

1. The knowledge base is rebuilt from sources plus the new fact, and the knowledge version goes up.
2. Only decisions whose dependencies intersect the change are re-checked. Gaps also register the
   terms that *could* resolve them, so a correction can reopen a line that was withheld.
3. Re-checked lines that are still not accepted are redrafted in one batched call.
4. A rule status change re-checks nothing unless it crosses a trust boundary (active ↔ inactive or
   trusted ↔ untrusted), because otherwise no check outcome can change.

In the sample, the linguist's correction of `tamba` affected 1 of 12 drafted lines (S003). It was
redrafted and its expert question narrowed from "welcome home" to "welcome". The retraction of E15
affected 0 lines, because E15 had been excluded as suspect since knowledge version 1.

## 9. Trust boundaries

- Pack text, retrieved text and model output are **data**. `guard.py` quarantines instruction-like
  text before it reaches any prompt (Dictionary A's "NOTE TO AI SYSTEMS", viewer comment V06) and
  keeps the entry itself, so a hostile note cannot delete a valid meaning.
- The model sees only sanitised text and the current evidence view, never the answer key.
- Nothing is sent anywhere by default. Replay mode is fully offline. The live providers send prompts
  to Anthropic; the brief's privacy rule means using a no-retention/no-training account for real material.

## 10. Scale: 5,000 episodes, 40 dialects

- **Learning is per dialect, not per episode.** The rules and lexicon are built once per dialect,
  versioned, and reused across episodes. Model calls then grow with scenes, not with the pack.
- **The dependency index becomes a real index.** (term|rule|evidence) → decision ids in a database,
  so a correction to one word finds its hundreds of subtitle lines in one query.
- **Review is the bottleneck, and should be.** Questions are deduplicated per dialect: "is `lavo`
  bring?" is asked once, not once per episode, and the answer becomes a correction event.
- **What fails first:** the verifier's English normaliser (a small lemmatiser and synonym table)
  and the one-word-per-token alignment. Both need proper NLP tooling before real scale.
