# Fix 005: `entity_service_consistent` flag

## Why

Question raised directly: now that entity extraction and structured intent are
two separate steps, should the LLM also confirm/compare its findings against
entity extraction's, as another precaution layer?

Considered and rejected: an LLM re-deriving entities independently and
reconciling disagreement is exactly the design this pipeline was built to
avoid. Entities are passed into `structured_intent.py`'s prompt as trusted
hints ("treat these as given, do not contradict or re-derive them") specifically
so nothing downstream re-derives and possibly contradicts them -- see the module
docstring and `fix-002`. v1 had the alternative (independent signals that could
disagree) and needed a dedicated validator rule just to catch "service is null
but a municipal_service entity is present." A second LLM pass also isn't
guaranteed to catch anything the first one missed (same model, same blind
spots) and would double the per-message latency this pipeline already spends.

## Fix

Added `_entities_agree_with_service(service, entities)` in `structured_intent.py`
-- a **code-only, no-LLM-call** check, not a second model opinion. Compares the
final (already `fix-003`-validated) `service` value against the document/service-
typed entities from `entity_extraction.py`:

- `service` is `None` and a document/service entity exists -> `False` (the
  entity layer found something concrete, the intent layer never committed to
  it -- mirrors a rule v1's validator already enforced).
- `service` is set but no document/service entity supports it -> `False`.
- Either side supports the other (substring overlap, either direction) -> `True`.
- Neither side claims anything -> `True` (nothing to disagree about).

Result is logged as a new `entity_service_consistent` field on every record --
built for human review during evaluation (fast to filter/sort on in the JSONL
log), not for the pipeline to act on automatically.

## Evidence

Unit-tested all 4 branches directly (no LLM needed, instant):

| service | entities | expected | actual |
|---|---|---|---|
| `None` | `[{document}]` | `False` | `False` |
| unrelated real value | `[{document}]` | `False` | `False` |
| a value | `[{date}]` (no doc/service) | `False` | `False` |
| `None` | `[]` | `True` | `True` |

Also ran through the real pipeline on 3 messages:

- Gas-connection cost question: `service` exactly matched its entity -> `True`.
- Business-license message: `service` ("άδεια λειτουργίας καταστήματος") was
  *longer* than its entity ("άδεια λειτουργίας") -- correctly still `True`,
  since the bidirectional overlap check recognizes an extension as agreement,
  not a mismatch.
- "Γεια σας": nothing found on either side -> `True`.

## Important limitation, not solved by this flag

Tested the "κοινωνικό επίδομα" message that's had a known span-precision issue
since `fix-001` (extracts the generic word "αίτηση" instead of the real service
name). Both `entities` and `service` agreed on `"αίτηση"` this time -- so the
flag correctly reported `True`, because there genuinely was no disagreement
between the two layers. **They made the same mistake together.**

This is the flag's real boundary: it catches when the two layers *contradict*
each other, not when they're *confidently wrong in the same way*. Consistency
is not correctness. Still useful as a cheap first filter during log review, but
not a substitute for actually reading flagged-`true` records too, not just the
`false` ones.
