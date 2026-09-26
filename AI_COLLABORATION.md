# AI collaboration log

This project was built AI-first, on purpose. Here is who did what, stated plainly so no one has to guess.

## Who did what

| Who | Did |
|---|---|
| **Me (Ali)** | Decided to take on the assignment and chose Nadi-9. Asked STAGE for the missing evidence pack. Set the ground rules: be open that the pack is synthetic, never invent evidence, never ship a line the checker has not passed. Approved publishing the repo and submitting it. |
| **Claude Code (Claude Opus 5.5)** | Designed the synthetic pack and its traps, the architecture and every module in `src/`, the tests, the scorer and these notes. Ran each change against the pack and found and fixed the bugs listed below during its own verification runs. |
| **Claude, answering offline prompts** | Acted as the agent's *drafting model* for the sample run (`replay/*.json`). |
| **Claude Omni** (Claude Code over an OmniRoute gateway) | Given a written brief for the test suite. Its output was rejected (row 7 below). |

I did not write or review the code line by line before submitting. What I bring to the discussion is
the approach, and I'm working through the code now so I can explain and change any part of it.

## How the sample run's model answers were produced

No Anthropic API key was available, and `claude -p` could not run nested inside the Claude Code
session. So instead of faking a live call, the pipeline got a file-based loop:

1. `python run.py run ... --record-missing` writes each prompt the pipeline needs to
   `replay/pending/<key>.prompt.txt` and carries on safely (those lines abstain).
2. Claude answered each prompt file as the drafting model, from the prompt alone.
3. `tools/answer.py` stored each answer with the SHA-256 of the exact prompt.
4. The run was repeated. Later prompts depend on earlier answers, so this took five rounds.

The recorded answers are real model output for the real prompts, not hand-edited fixtures. The
surprise events in `events/demo_events.json` (the fake plural rule, the outage) are labelled
injections, not presented as something the model did on its own. The live providers
(`--provider anthropic|claude-cli`) record in the same format.

## What went wrong during the build, and how it was caught

All of these were found by Claude Code while checking its own output: comparing results against the
traps the pack was designed to contain, and reading the prompts and logs the pipeline produced.

| # | What happened | How it was caught | Fix |
|---|---|---|---|
| 1 | Interview and expert evidence was linked to a meaning by **word overlap**. "younger brother" (Dictionary A's poisoned entry for *anno*) picked up support from an interview line about an "elder brother", so *anno* came out CONTESTED instead of POISONED. | The first lexicon dump did not match the traps the pack was built with | Evidence must contain a **whole meaning phrase** (`_phrase_in` in `lexicon.py`) |
| 2 | Meaning phrases shorter than 3 characters were filtered out. That silently dropped "be", so *si* ("be/was") lost its interview support. | Reading the translation prompt the pipeline actually sent | Filter lowered to 2 characters |
| 3 | **Any** rule status change re-checked lines. Retracting E15 re-checked 10 of 18 lines, though no check outcome could change. | The re-plan log showed 10 affected lines for an example already excluded | Only a change that crosses a trust boundary triggers re-checks; the run now reports `RETRACTION_ALREADY_HANDLED` and 0 affected |
| 4 | When a redraft failed during an outage, the placeholder **overwrote the earlier valid draft**. | Walking through the outage path in `_draft` | Outages keep the earlier proposal |
| 5 | Expert questions put a missing "even" ahead of the checker's rejection of the whole draft. | Reading the review queue as a linguist would | Checker failures now come before partial gaps |
| 6 | **The drafting model** rendered "call on the phone" as *phone se boliriji* ("spoke by phone"), a plausible paraphrase based on interview I2. | The independent verifier rejected it: *boli* is only attested as say/tell/speak | The repair moved "call" to a gap and passed the paraphrase to the reviewer as a candidate instead of shipping it |
| 7 | **Claude Omni**, briefed to write the required tests, started with an unrequested `test_util.py`. 3 of its 11 tests failed on its own wrong expectations (it expected `lemma("tried") == "tri"`). | Its file was run before anything was accepted | The worker was stopped, the file deleted, and the suite written in the main session against the brief |
| 8 | The exact-match score in `eval/score.py` (13/13 drafts match the key) looked like a quality metric. | It is circular: the same model wrote the key and the drafts | Labelled in the scorer output as "not a quality score" |

## What was deliberately not accepted

- **Letting the model's confidence count.** The drafting model rated itself ≥ 0.80 on S006 and S015.
  Both depend on a loanword rule an expert disputes for rural speech. Self-ratings are recorded and
  reported, never used; a test enforces it.
- **Filling gaps with fluent guesses.** For "welcome home", "every", "already" and the idiom in S009,
  a plausible Nadi-9 sentence could be built from the lexicon. Each one would be an invention, so
  those lines abstain and the candidate wording goes into `assumptions` for the linguist.
- **Treating the biggest dictionary as the default.** Dictionary A covers the most words; its weight
  comes from measured agreement (85%), not size.

## How AI output was checked

- Every change was run end to end against the pack. `eval/score.py` checks all 13 planted traps
  after each run.
- 33 tests in `tests/` cover the four behaviours the brief names (conflict, unsupported term,
  correction event, tool failure), plus poisoning, injections, respect, budget, determinism and
  replay drift. They run in about 1.5 seconds.
- Every model claim the pipeline relies on is re-checked in code: rule quotes are matched verbatim,
  rules are tested against examples, and drafts go through `verify.py`.
