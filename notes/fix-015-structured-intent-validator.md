# Fix 015: centralize structured-intent guardrails into validator.py

## Why

Raised in `backlog.md` after comparing against v1's `structured_intent/validator.py` -- a single function every layer's output passes through (required fields, enum membership, cross-field consistency), versus v2's equivalent checks being scattered across `_is_valid_service`/`_is_valid_entity` (two files) and `_entities_agree_with_service` (a soft, ad hoc flag). Nothing was *broken* -- this is a consolidation, and the one thing v2 genuinely lacked a guardrail for at all: the upcoming rule-based fast path (`fix-016`) needed something to validate its output against before it could ever be trusted, and no such thing existed yet.

## Design

`pipeline/validator.py` -- new module, not a port of v1's `validator.py` (v1 validates a multi-`requests` envelope with `needs_clarification`/`search_terms` v2's schema doesn't have). Checks: required fields present, `intent`/`action`/`answer_type` enum membership, well-formed/typed/deduplicated entities, `constraints` shape, and one cross-field rule (`service` null while a document/service entity is present -- mirrors `_entities_agree_with_service`, kept as an *additional* check, not a replacement).

Deliberately **not** ported from v1: the "`answer_type` must match a fixed mapping for this `intent`" rule. v1 folds "what information the user wants" into `intent` itself (`find_cost`, `find_deadline`, ...), so that mapping is load-bearing there. v2 keeps `intent` coarse and lets `request_service`/`question` legitimately pair with any of the 6 `answer_type` values -- there's no real 1:1 mapping in v2's data to enforce, and inventing one would risk flagging correct records as invalid.

**Circular-import correction, caught before anything ran:** the first draft had `validator.py` import `INTENTS`/`ACTIONS`/`ANSWER_TYPES` directly from `structured_intent.py`. That's a cycle -- `structured_intent.py` needs to import `validator.py` back, to call it on the fast path's candidate record. Fixed by pulling the three taxonomy lists out into a new leaf module, `taxonomy.py`, that both `structured_intent.py` and `validator.py` (and `intent_rules.py`, which hit the identical problem seconds later) import from, with nothing importing back from it -- same principle `date_rules.py` already models for pulling a sub-concern out of a module that would otherwise need to import its own dependent.

**Hard vs. soft (the question `backlog.md` explicitly left open) -- resolved as a deliberate split, not one global answer:**
- **Existing LLM path** (`_normalize` / `_finalize`, `source="llm"`): soft. `validate_structured_intent(...)` runs and its output is attached as `record["validation_errors"]` for logging -- never raises. `_normalize` already coerces every field to a safe default before this runs (`intent if intent in INTENTS else "other"`, etc.), so this should return `[]` on this path by construction. Making it hard here would be a real behavior change (crash vs. this pipeline's established never-raise posture, see `ollama_client.py`'s docstring) for no corresponding new safety.
- **Fast-path candidate** (`_try_fast_path`, `source="rule_fast_path"`): hard, via `validate_or_raise`, called one frame up inside a `try/except` that treats a validation failure exactly like an abstain (fall through to the LLM). Safe to be strict here specifically because a failure never surfaces to a user -- it only costs that one message's latency win. This is the one genuinely new use case that had no guardrail before.

`entity_service_consistent` is untouched -- `validator.py`'s cross-field check is additional, not a replacement for a working, already-tested field.

## Evidence

`pipeline/tests/validator_selftest.py` -- one known-good record (zero errors) plus 6 deliberately-broken variants, each individually caught, plus both `validate_or_raise` calling-convention cases (raises on bad input, doesn't raise on good input):

```
[OK] known-good record: errors=[]
[OK] missing field (service): errors=['missing field: service', 'service is null but a document/service entity is present']
[OK] intent outside allowed vocabulary: errors=["intent not in allowed vocabulary: 'not_a_real_intent'"]
[OK] action outside allowed vocabulary: errors=["action not in allowed vocabulary: 'teleport'"]
[OK] duplicate entity: errors=["duplicate entity: {'text': 'Βεβαίωση Μόνιμης Κατοικίας', 'type': 'service'}"]
[OK] constraints not a list: errors=['constraints must be a list of strings']
[OK] service is null but a service entity is present: errors=['service is null but a document/service entity is present']
[OK] validate_or_raise raised as expected: intent not in allowed vocabulary: 'not_a_real_intent'
[OK] validate_or_raise did not raise on a known-good record

ALL PASS
```

**End-to-end confirmation, corrected from an initial wrong claim:** the first draft of this doc claimed every LLM-path record in the post-wiring eval batch comes back with `validation_errors: []`. That's false, checked and caught before shipping the claim: 2 of 17 LLM-path records in the first 40-case batch (`pipeline/logs/eval_log_run1_2026-08-06_fast-path.jsonl`) came back non-empty --

```
input: Χρειάζομαι βεβαίωση χιλιομετρικής απόστασης από το σπίτι μου ως το σχολείο.
validation_errors: ['service is null but a document/service entity is present']
entity_service_consistent: False

input: Θέλω πιστοποιητικό μητρώου αρρένων για τον γιο μου.
validation_errors: ['service is null but a document/service entity is present']
entity_service_consistent: False
```

Not a validator bug, and not a new problem either: both are genuine, pre-existing LLM inconsistencies (a real `document` entity found, but the LLM's own `service` field came back null anyway) that `entity_service_consistent` was already flagging as `False` before this fix existed. The two independently-computed checks agree exactly on both cases -- real evidence the centralization is coherent, not that it introduced a new failure mode. Every OTHER LLM-path record across both full batches (see `fix-016`) came back clean. Corrected here rather than left wrong, since an unverified "always clean" claim is exactly the kind of thing this project's own testing discipline exists to catch before it ships.

## What this doesn't do

No hard validation anywhere a user could hit it. If `intent_rules.py` (the fast path) or a future third source ever produces a genuinely malformed record, `validate_or_raise` stops it from reaching `answer_composition.py` -- but that failure is invisible to the caller, converted into "use the LLM instead." There is currently no path where `StructuredIntentValidationError` can propagate out of `resolve_structured_intent` at all.
