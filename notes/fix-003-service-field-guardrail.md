# Fix 003: `service` field had no validation guardrail

## What we saw

Unlike `entities` (checked against the original message via `_is_valid_entity`),
the `service` field was passed straight through from the LLM with no check at
all. Across several batches this produced values with no relationship to the
input whatsoever:

- `"marriage_license"` -- English, snake_case, not present anywhere in the Greek
  input.
- `"document"` -- the entity *type*, not an actual service name (seen 3 times).
- `"payment"` -- English generic noun, not a real service name.
- `"pistopoiitiko genisi"` -- a Greeklish transliteration of "πιστοποιητικό
  γέννησης", not the actual Greek text.

This was the one item in `open-weakpoints.md` that recurred on nearly every
batch, unlike everything else which was intermittent -- so it became the
priority fix.

## Fix

There's no KB lookup yet to check `service` against real municipal service names
(that's a later pipeline step, not built yet), so the cheapest real guardrail
available now is the same one `entities` already uses: require `service` to
actually appear in the original message (accent- and case-insensitive).

Rather than duplicate the accent-stripping comparison logic, promoted
`entity_extraction.py`'s private `_normalize` to a public `normalize_for_comparison`
and imported it into `structured_intent.py`. Added `_is_valid_service(service,
original_text)` there, used inside the existing `_normalize` (the result-builder
function -- unrelated name collision with the text-normalizing helper, kept the
existing name since it's the file's own established meaning). A `service` that
fails the check becomes `None` instead of being kept.

Note: this only catches a fully *invented* value, not a *wrong but real* one
(e.g. the model picking a different real phrase from the message than the ideal
one). That's a smaller, harder problem than what we actually observed, so not
addressed here.

## Evidence

Re-ran the exact messages that had previously produced each of the 4 bad values,
plus one message that had a genuinely correct `service` value, to check for false
positives:

| Message | Before | After |
|---|---|---|
| "...άδεια γάμου και να μάθω πόσο κοστίζει" | `"marriage_license"` | `None` |
| "Ο λογαριασμός ύδρευσης...λανθασμένος" | `"document"` | `None` |
| "...πρόστιμο τροχαίας...περασμένη Τρίτη" | `"payment"` | `None` |
| "...πιστοποιητικό γέννησης...δημαρχείο Ηρακλείου" | `"pistopoiitiko genisi"` | `None` |
| "...σύνδεση φυσικού αερίου;" (genuinely correct before) | `"σύνδεση φυσικού αερίου"` | `"σύνδεση φυσικού αερίου"` (unchanged) |

All 4 bad values now correctly reject; the 1 good value is unaffected.
