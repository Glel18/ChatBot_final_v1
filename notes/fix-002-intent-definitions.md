# Fix 002: intent classification missing category boundaries

## What we saw

Second batch of 5 messages through `run.py`, after fix-001. Two clear misses:

- "Δεν έχω λάβει απάντηση στο αίτημά μου εδώ και δύο εβδομάδες." (no response in
  two weeks -- a textbook complaint) -> classified `intent: "question"`, not
  `"complaint"`.
- "Πόσο κοστίζει η έκδοση πιστοποιητικού γέννησης;" (cost question) ->
  classified `intent: "other"`, not `"question"`.
- "Γεια σας" (plain greeting) -> also `"question"`.

Pattern: `question` looked like it was acting as a default catch-all whenever a
message wasn't clearly `request_service`, even when `complaint` or `other` fit
better.

## Diagnosis / design question

Raised directly: if every miss gets fixed by adding another few-shot example,
doesn't that not scale, and risk the model pattern-matching on keyword/phrasing
overlap with the examples rather than generalizing? (We'd already seen a preview
of this in fix-001: an example nearly identical to a test message "fixed" that
one case suspiciously well.)

Conclusion: examples teach one specific sentence shape. A category **definition**
teaches the general rule, so it should generalize across phrasing instead of
memorizing surface patterns -- try that first, before reaching for more examples.

## Fix

Replaced the bare `Allowed intent values: request_service, question, complaint, other`
list in `structured_intent.py`'s prompt with one phrasing-based rule per category
(`INTENT_DEFINITIONS`):

- `request_service` -- statement of desire/intent ("I want to...", "I need to..."),
  the municipality should DO something now.
- `question` -- asking for information (cost, deadline, requirements, location,
  hours, status), usually phrased as a question.
- `complaint` -- reporting a problem, delay, error, or dissatisfaction about
  something that already happened.
- `other` -- greetings, small talk, anything else.

No new examples added.

## Evidence

Zero new examples, and it fixed both real misses plus a third inconsistency we
hadn't explicitly flagged yet:

| Message | Before | After |
|---|---|---|
| "no response in two weeks" | `question` | `complaint` |
| "cost of birth certificate?" | `other` | `question` |
| "renew my ID" (already correct) | `request_service` | `request_service` (unchanged) |
| "when does my license expire?" (already correct) | `question` | `question` (unchanged) |
| "what documents do I need for a birth certificate?" | `request_service` | `question` (see note) |

Note on the last row: this flipped from `request_service` to `question` under the
new, more consistent rule (it's phrased as a question). This is a judgment call,
not a clear bug -- v1's schema had grouped this specific pattern under
`request_service` via its `answer_type`. Decided in favor of the more internally
consistent rule (interrogative phrasing -> `question`) rather than special-casing
it back.

Batch 3 (see `open-weakpoints.md` for what's still open) then showed the
`complaint` definition generalizing to two brand new phrasings sharing almost no
vocabulary with the original miss or with each other ("the water bill I received
is wrong", "the street lighting hasn't worked in a week") -- both correctly
classified `complaint` off the one-line rule alone. Real evidence the
definitions approach generalizes rather than keyword-matching.
