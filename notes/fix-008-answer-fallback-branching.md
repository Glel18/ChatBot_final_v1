# Fix 008: four-way branch for `kb_match is None`

(Written retroactively during a notes review -- this was built and tested at
the time, referenced by `fix-009` and inside `answer_composition.py`'s own
docstring, but the write-up itself was never actually created. Recorded now
so the reference isn't pointing at nothing.)

## Why

`fix-007` only handled the case where `kb_match` was populated. Testing
showed `kb_match is None` was actually the *majority* of logged messages, not
the exception -- and it isn't one situation, it's (at least) four different
ones that need different responses, not one generic "sorry" message:

- `intent == "complaint"` -- not a KB-matching problem at all, needs
  acknowledgment, not a service lookup.
- `intent == "other"` -- small talk / greetings, also not a KB-matching
  problem.
- `service is None` -- we genuinely don't know what the user wants. The
  honest response is to ask, not guess at an answer.
- `service` is set but no KB title matched confidently -- a real gap, either
  genuinely missing from this KB (e.g. gas connection, confirmed absent) or a
  near-miss the gazetteer couldn't confirm.

## Fix

`compose_answer` in `answer_composition.py` branches on all four, each with
its own plain template, no LLM call anywhere:

- complaint -> acknowledgment + `PHONE_FALLBACK` (the real number already
  used in `gui.py` for the same purpose, not invented for this file).
- other -> generic "I'm here to help with Heraklion municipal matters" reply.
- `service is None` -> asks for clarification -- and references a found
  entity by name if one exists, even though `service` itself didn't resolve
  (e.g. "κοινωνικό επίδομα" -> entity "αίτηση" found but too generic to
  validate as a real service name), rather than a bare "what do you mean?".
- `service` set, no match -> names what was understood, points to the phone
  number, doesn't invent cost/procedure content that isn't in this KB.

Deliberately NOT using an LLM to fill the "no exact match" case -- that would
reintroduce the exact hallucination risk `fix-003`'s guardrail exists to
prevent, this time in the final answer text. Ship the honest version, see
from the log how often each branch is actually hit, decide later if it's
worth the risk.

`compose_answer` now always returns something (`{"text": ..., "source": ...}`)
instead of `None` -- `source` records which branch fired, logged on every
record via `run.py` so the eval log shows at a glance how messages are being
handled without re-deriving it from intent/service/kb_match each time.

## Evidence

Unit-tested all four branches with synthetic records, then confirmed
end-to-end through the real pipeline on 3 live messages:

- a complaint with no `kb_match` -> `complaint_acknowledgment`
- "Πρέπει να πληρώσω τα δημοτικά τέλη μέχρι πότε;" (service never resolved)
  -> `clarification_needed`, generic phrasing (no entity was found to
  reference for this one)
- "Γεια σας" -> `small_talk`

All three matched the intended branch on the first real run.

## What this doesn't do

Complaint precedence here (checking `kb_match` before intent) turned out to
be the wrong call on further testing -- see `fix-009`, which reversed it.
