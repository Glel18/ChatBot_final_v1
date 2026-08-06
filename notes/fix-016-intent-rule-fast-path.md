# Fix 016: rule-based fast path for intent/action/answer_type/service

## Why

Measured baseline (`pipeline/logs/eval_summary_2026-08-06.md`, 34 real messages): total pipeline 10.1-30.2s (mean 19.7s), of which `structured_intent_llm` -- the single LLM call resolving `intent`/`service`/`action`/`answer_type`/`constraints` -- runs unconditionally, every message, averaging ~11.5s on its own. `backlog.md` raised this after a side-by-side comparison against v1's `structured_intent/rule_engine.py`, which resolves the same kind of thing via weighted keyword-indicator scoring with a confidence gate, no LLM call, verified by re-running v1's own gold-set eval directly: 16/16 correct.

## Design

`pipeline/intent_rules.py` -- new module, mirroring `date_rules.py`'s separation (pure rules, no model call, independently testable). Adapts v1's *mechanism* (word-boundary phrase matching weighted by phrase word-count, top-score-and-margin abstain gate), not its indicator phrases -- v1 has no `complaint` intent at all (folds fault reports into `request_service` + action `declare`), so its actual phrase lists (bare "θέλω" as a `request_service` indicator) were never tested against v2's specific complaint-vs-request_service ambiguity and would have reintroduced it. Every indicator phrase was built fresh for v2's 4 intents / 7 actions / 6 answer_types.

**The `service`/`constraints` gap a naive port misses:** v1's rule engine never resolves `service` (that's a separate layer there) -- skipping `structured_intent_llm` without also resolving `service` some other way wouldn't actually save the latency this exists for. Fixed by deriving `service` directly from `entities` (already computed by `extract_entities` before this runs, already self-validating), and **abstaining** (`abstain_reason="no_service_entity"`) when the resolved intent is `request_service`/`question` and no such entity exists -- the only two intents where `service`/`kb_match` materially affects the composed answer. `constraints` is always `[]` on a fast-path commit, an explicit trade-off, not a silent drop.

**Circular import, caught before running anything:** `intent_rules.py` and `validator.py` (`fix-015`) both need the same taxonomy `structured_intent.py` owns, and both get imported BY `structured_intent.py` -- importing the vocab back from there would cycle. Fixed by extracting `INTENTS`/`ACTIONS`/`ANSWER_TYPES` into a new leaf module, `taxonomy.py`.

**No bare "θέλω"/"θέλω να" anywhere in `request_service`'s indicators** -- the deliberate structural fix for `open-weakpoints.md` #7. Every phrase names a concrete verb ("θέλω να κάνω αίτηση", "θέλω να πληρώσω", ...), so a real complaint like "θέλω να υποβάλω παράπονο..." scores 0 for `request_service` and wins cleanly under `complaint` ("παράπονο", "θέλω να υποβάλω παράπονο") -- not a tuned threshold, a removed signal. Same approach for actions: `schedule` ("κλείσω ραντεβού") and `cancel` ("ακυρώσω") share no vocabulary, directly targeting the `fix-011`/#5 regression.

**Wiring** (`structured_intent.py`): `resolve_structured_intent` tries `_try_fast_path` first; on a `resolve_intent_fast` commit, the candidate record is built via a new shared `_finalize` (factored out of `_normalize`, used by both paths so they can't drift out of sync) and passed through `validator.validate_or_raise` as a **hard** gate -- a validation failure here is treated exactly like an abstain, never surfaced. Falls through to the unchanged LLM path otherwise. Every record gets `intent_source` ("rule_fast_path" or "llm"), mirroring `answer_source`'s existing convention.

## Evidence

**Standalone gold-set** (`pipeline/tests/intent_rules_eval.py`, no LLM calls, fully deterministic): 11/11 cases pass, including the three regression gates checked individually:
- **#7**: "Θέλω να υποβάλω παράπονο..." → `intent="complaint"`, not `request_service`.
- **#5**: same message with vs. without a service entity correctly abstains (`no_service_entity`) or commits to `action="schedule"`; "Θέλω να ακυρώσω..." commits to `action="cancel"` -- no shared vocabulary between the two.
- **#3**: both greeting+question cases correctly rank `question` above `other` in `scores` (checked directly, since both abstain on `no_service_entity` -- a generic hours/info question has no document/service entity to derive, by design).

**End-to-end, run twice** (`pipeline/logs/eval_log_run1_2026-08-06_fast-path.jsonl`, `..._run2...jsonl`, 40 real messages each, real LLM calls where the fast path doesn't fire):

| | Run 1 | Run 2 |
|---|---|---|
| `intent_source` split | 23 fast-path / 17 llm | 23 fast-path / 17 llm |
| fast-path mean `total_pipeline_ms` | 9,140 | 6,609 |
| llm-path mean `total_pipeline_ms` | 24,474 | 15,017 |

**Reproducibility**: 39/40 records identical across both runs (`intent_source`/`intent`/`action`/`answer_type`/`service` all matching). The one mismatch was on the **LLM path** (a `service` value differing between runs for "Θέλω να ενοικιάσω τάφο..."), consistent with pre-existing LLM/entity-extraction variance this pipeline already has -- not something the new fast-path code introduced (the fast path itself is pure Python; same input always produces the same output). Both runs agreed on which 23/40 messages hit the fast path at all.

**The #5/#7 gates confirmed live, not just in the isolated gold-set, twice:**

```
Θέλω να ακυρώσω το ραντεβού μου.                    -> action=cancel   (both runs)
Χρειάζομαι να κλείσω ραντεβού για την Δευτέρα.      -> action=schedule (both runs)
Θέλω να υποβάλω παράπονο για τον θόρυβο στη γειτονιά. -> intent=complaint (both runs, both category tags it appears under)
```

The second line is the *exact* message from `fix-011`'s original bug report (misclassified `cancel` instead of `schedule` on the LLM path) -- confirmed genuinely fixed end-to-end, not just theoretically avoided, since real `entity_extraction` does produce a `service`-typed "ραντεβού" entity for this message, letting the fast path commit.

**Latency**: fast-path messages averaged 6.6-9.1s total vs. 15.0-24.5s for LLM-path messages in the same batches -- roughly a 55-65% reduction for the ~58% of messages (23/40) that hit the fast path in this batch. Consistent with, though not identical to, the ~11.5s `structured_intent_llm` savings the backlog projected (the fast path also can't avoid `entity_extraction`'s own unconditional LLM fallback call, so the delta reflects that shared cost on both sides).

**Validator side effect, corrected honestly rather than left wrong:** the LLM path's `validation_errors` field caught 2 real (pre-existing, not new) cross-field inconsistencies in run 1 -- see `fix-015` for detail and the correction to that doc's initial overclaim.

## What this doesn't fix

- **#3** (greeting-prefixed questions misclassified) -- the fast path's *ranking* is provably correct (question outranks other in `scores`), but both real-world #3 cases abstain on `no_service_entity` and fall through to the unchanged LLM, so the user-visible outcome for these specific messages is unchanged from before this fix.
- **#1, #2, #8** (fee/payment entity type gap, multi-entity recall, span truncation) -- none touched; these are `entity_extraction.py` concerns, out of scope here. #8 in particular directly limits fast-path coverage: a truncated `service` (e.g. "ανακύκλωσης" instead of "κάδου ανακύκλωσης") is still what `_derive_service` picks up, for better or worse.
- **#6** (compound messages, no clause-splitting) -- not addressed at the root. One incidental observation: the tested compound case now commits via the fast path with a populated `service` and a `cost` `answer_type` (previously: `clarification_needed` on the LLM path) -- arguably a better fallback for that one case, but not a fix for the underlying blending problem.

---

## Patch notes (added after the original writeup above -- nothing above this line was changed)

### 2026-08-06, run 3 + a genuine same-question pre/post comparison

Ran the full batch a third time (`pipeline/logs/eval_log_run3_2026-08-06_fast-path.jsonl`) and, separately, pulled the archived **pre-fast-path** baseline (`pipeline/logs/eval_log_archive_2026-08-06_pre-fast-path.jsonl` -- the last eval run before this fix existed, 34 messages) and matched it against all three post-fast-path runs **by exact input text**, not position. `run_full_eval.py`'s `CASES` grew from 34 to 40 between that baseline and today (6 new fast-path-tagged cases added, 4 of which duplicate existing messages) -- matching by text instead of index gives a clean 34-message overlap between the old baseline and every new run, plus 2 genuinely new messages with no baseline to compare against.

**Three-way reproducibility, run1 vs run2 vs run3:** `intent_source` split identical across all three (23 fast-path / 17 llm, every run). Across all 120 record-pairs compared (3 pairwise run comparisons × 40 messages), only 3 differed -- and all 3 were on the **LLM path**, never the fast path (which is pure Python and reproduces exactly by construction). Consistent with the pre-existing Ollama/entity-extraction variance already known about, not anything this fix introduced.

**The real finding -- same-question, old-code vs new-code, not just new-code-vs-itself:** matching the pre-fast-path baseline against run1/2/3 by exact message text surfaces something the earlier (post-fast-path-only) comparisons couldn't show: **the baseline itself still had the #5 and #7 bugs**, on the literal bug-report messages, confirmed identically across all three new runs:

```
"Χρειάζομαι να κλείσω ραντεβού για την Δευτέρα."
  pre-fast-path baseline:  action=cancel     <- the fix-011 bug, still live in the baseline
  run1 / run2 / run3:      action=schedule   <- fixed, all three runs agree

"Θέλω να υποβάλω παράπονο για τον θόρυβο στη γειτονιά."
  pre-fast-path baseline:  intent=request_service, service=None   <- the #7 bug, still live
  run1 / run2 / run3:      intent=complaint, service='παράπονο'   <- fixed, all three runs agree
```

This is stronger evidence than the original writeup had: not "the fast path resolves this correctly" in isolation, but "the exact same input, through the exact same pipeline entrypoint, produced the documented bug before this fix and the correct answer after it" -- a real regression test, not just a forward-looking gold-set case.

**Other same-question diffs** (8-9 of 34 messages changed some field vs. baseline, consistent count across runs): mostly cosmetic (`answer_type` shifting, e.g. `other`→`procedure`) or `service` going from `None` to populated (an improvement -- "θέλω να κάνω αίτηση για άδεια γάμου και να μάθω πόσο κοστίζει" now carries `service='άδεια γάμου'` instead of nothing). One is a known, pre-existing issue resurfacing in a different shape, not a new one: the recycling-bin message's `service` changed from `'μεταφορά'` (baseline) to `'ανακύκλωσης'` (all three new runs) -- still `open-weakpoints.md` #8's span-truncation gap, just truncating differently, not newly broken. `kb_match` hit rate held at 8/40 across all three new runs -- zero new false positives or negatives from switching resolution paths.

**Latency, same 34 questions only (apples to apples, excludes the 2 fast-path-only additions):**

| | pre-fast-path baseline | run1 | run2 | run3 |
|---|---|---|---|---|
| mean `total_pipeline_ms` | 23,222 | 16,867 | 10,889 | 15,843 |
| fast-path subset mean (n=17) | -- | 9,261 | 6,762 | 8,507 |
| llm-path subset mean (n=17) | -- | 24,474 | 15,016 | 23,179 |

27-53% overall latency reduction on the identical 34-message set across the three runs (absolute times vary run to run with system/Ollama load, same as every latency number in this project so far -- the *relative* reduction and the *correctness* findings are the load-bearing evidence, not any single absolute number).
