# SYNTHETIC PACK — NOT STAGE MATERIAL

The official Nadi-9 assignment pack (approved examples, Dictionaries A and B, grammar note,
audio interviews, viewer feedback, expert notes, episode transcript) was requested from STAGE
on 25 Sep 2026 and had not arrived by the time this build started.

Everything in this folder was written for this submission by Claude Code (see `AI_COLLABORATION.md`) to exercise the pipeline. It imitates
the *shape and difficulty* the brief describes:

| Brief says | Synthetic pack contains |
|---|---|
| 20 approved examples, two may be challenged | 20 examples; two contain deliberate mistakes |
| Dictionary A: broad, reliability unknown | 46 entries, four wrong on purpose, one carries an injected instruction |
| Dictionary B: smaller, community linguist | 22 entries, disagrees with A on several terms |
| Grammar note: incomplete rules | Prose rules with gaps (imperative, hortative, idioms, plural) |
| 5 audio interviews | 5 interviews; 4 as transcripts, 1 audio-only (transcription tool fails) |
| Viewer feedback: signal + noise | 6 comments incl. one prompt injection |
| 3 experts who disagree | 3 expert notes with two real disagreements |
| Episode with humour, relationships, code-switching | 18 timed lines, 5 characters, 3 scenes |

The answer key used to design the traps lives in `eval/answer_key.json`,
outside this folder. The pipeline never reads it; a test enforces that.

When the real pack arrives, write an adapter from its format to the schema in
`ARCHITECTURE.md` §2. The agent logic does not change.
