# notes/

Running log of what we build, fix, and find while testing the pipeline in `pipeline/`.

- `fix-NNN-*.md` — one file per change made to the pipeline. Each covers: what was
  broken, how we diagnosed it, what changed, and the before/after evidence that
  shows it actually worked.
- `open-weakpoints.md` — living list of known issues found through testing that
  haven't been fixed yet. Updated as new batches surface new gaps, and trimmed as
  items get fixed (which then gets its own `fix-NNN` entry).
- `backlog.md` — side objectives and ideas that come up while working on
  something else: real and worth doing, but deliberately deferred so they
  don't fragment whatever's actively in progress. Pull an item out into its
  own `fix-NNN` when it's actually picked up.
- `tried-and-failed.md` — approaches actually attempted (not just considered)
  that didn't hold up once tested, and got reverted or rejected. Different
  from `open-weakpoints.md` (known issues in what's shipped) — this is the
  record of dead ends, so the reasoning behind them isn't lost once the code
  moves past them.

Numbering in `fix-NNN` is chronological order, not severity.

`pipeline/` work is paused as of 2026-08-14, pending a better BERT model for
the other implementation (`connector.py`/`dimos-intent-model`). The
`integration-guide.md` and `pipeline-overview.md` docs that used to live here
were removed along with that pause -- the `fix-NNN` entries below remain the
record of what was built and why.

## Index of fix-NNN entries

One line each -- open the file for the full diagnosis, evidence, and
before/after. `fix-012` isn't a code change (see the file itself); logged in
the same sequence anyway since it changed what's known to be fixable.

| # | What it covers |
|---|---|
| [001](fix-001-entity-extraction-recall.md) | Entity extraction returning zero entities on obvious cases -- fixed via few-shot examples + accent-insensitive matching |
| [002](fix-002-intent-definitions.md) | Intent misclassification (complaint read as question, etc.) -- fixed via one-line definitions per intent instead of a bare word list |
| [003](fix-003-service-field-guardrail.md) | `service` field had no validation -- fixed via a substring-match guardrail |
| [004](fix-004-rule-gazetteer-entity-extraction.md) | Moved `date`/`document`/`service` extraction off pure-LLM onto rules + gazetteer, LLM as fallback only |
| [005](fix-005-entity-service-consistency-flag.md) | Added `entity_service_consistent` -- a code-only cross-check, not a second LLM opinion |
| [006](fix-006-kb-lookup.md) | Wired up step 4 (KB lookup) -- `kb_match` now carries a real title + URL |
| [007](fix-007-answer-composition.md) | Step 5, kb_match-present case -- template-only answer composition, no LLM |
| [008](fix-008-answer-fallback-branching.md) | Step 5, kb_match-absent case -- four-way branch (complaint/other/clarification/no-match) |
| [009](fix-009-complaint-precedence.md) | Complaints were getting wrong-purpose `kb_match` answers -- fixed by never checking `kb_match` for complaints |
| [010](fix-010-gazetteer-generic-term-stripping.md) | Wrong-purpose matches from shared generic administrative words -- fixed by stripping them before matching |
| [011](fix-011-actions-cancel-schedule.md) | Added `cancel`/`schedule` actions -- partial win, surfaced a new bug (`schedule` misclassified as `cancel`), still open |
| [012](fix-012-ipiresies-pdf-coverage-audit.md) | Not a fix -- audited a human-marked service-coverage PDF; separated genuine KB gaps (unfixable by us) from more wrong-purpose-match evidence (already-tracked problem) |
| [013](fix-013-gazetteer-best-match-word-overlap-gate.md) | Wrong-purpose `kb_match` (open-weakpoints #9) -- fixed by requiring 2+ shared content-word stems in `best_match`, the same protection `find_service_entity` already had; 14/15 known bad cases fixed, 1 documented residual |
| [014](fix-014-gazetteer-thin-title-overlap-requirement.md) | `fix-013`'s flat "require 2 shared words" made 7/164 KB titles with only 1 real content word permanently unmatchable -- fixed by scaling the requirement to what each title can actually offer |
| [015](fix-015-structured-intent-validator.md) | New `validator.py` -- centralizes scattered per-field guardrails into one module; hard-gate on the new fast path's candidate records, soft/logged on the existing LLM path |
| [016](fix-016-intent-rule-fast-path.md) | New `intent_rules.py` -- rule-based fast path skips the LLM entirely for confident messages (23/40 in testing, ~55-65% latency reduction); structurally fixes open-weakpoints #5/#7 for messages that reach it |
