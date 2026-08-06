# Fix 001: entity extraction returning zero entities on obvious cases

## What we saw

First batch of 5 test messages through `run.py`. 3 of 5 came back with `entities: []`
even though the message clearly contained one:

- "Θέλω να ανανεώσω **την ταυτότητά** μου." (renew my ID) -> `[]`
- "Θέλω να κάνω αίτηση για **κοινωνικό επίδομα**." (apply for a social benefit) -> `[]`
- "...αίτηση για **άδεια γάμου**..." (apply for a marriage license) -> `[]`

Only `date` and `location` entities were coming through; `document`/`service` were
failing specifically.

## Diagnosis

Called `ollama_client.call_ollama` directly with the exact prompt `entity_extraction.py`
was sending, before any of our own filtering ran. The raw model output was already
`{"entities": []}` -- so this was not `_is_valid_entity` rejecting a valid match, it
was the model itself under-triggering, zero-shot, on those two entity types.

## Fix

Two changes to `_build_prompt` in `entity_extraction.py`:

1. Added few-shot examples (a document-only case, a true-negative/greeting case).
   First attempt with **only single-entity examples introduced a new bug**: the
   model started returning exactly one entity per message even when two were
   present (it dropped a `date` entity it had previously caught correctly, once
   it started reliably catching the `service` noun in the same sentence). Fixed by
   adding a third example showing **multiple entities in one message**, plus
   explicit "extract ALL, not just one" wording.
2. Made the substring guardrail (`_is_valid_entity`) accent-insensitive. Testing
   surfaced the model returning `αιτηση` for a message containing `αίτηση` (dropped
   accent) -- the old plain case-insensitive substring check would have wrongly
   discarded that as a hallucinated span. Now strips diacritics (NFD-normalize,
   drop combining marks) on both sides for the comparison only; the entity's
   original text is still what gets stored.

## Evidence (before / after, real function calls)

| Message | Before | After |
|---|---|---|
| ανανεώσω ταυτότητα | `[]` | `[{"ταυτότητά", document}]` |
| αίτηση κοινωνικό επίδομα | `[]` | `[{"αίτηση", service}]` (span imprecise, see open-weakpoints.md) |
| ραντεβού Δευτέρα | `[{Δευτέρα, date}]` | `[{ραντεβού, service}, {Δευτέρα, date}]` |
| δημαρχείο Ηρακλείου | correct | still correct |
| άδεια γάμου + cost | `[]` | `[{"άδεια γάμου", document}]` (type debatable, see open-weakpoints.md) |

Recall problem (returning nothing) is fixed. Precision on exact span/type is not
perfect on every message -- tracked in `open-weakpoints.md` rather than chased
further here, to avoid overfitting the prompt to this specific test set.
