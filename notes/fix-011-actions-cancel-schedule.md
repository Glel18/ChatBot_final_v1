# Fix 011: added `cancel`/`schedule` to ACTIONS -- partial success, one new bug found

## What

Added `cancel` and `schedule` to `ACTIONS` (was `apply, renew, check_status,
pay, unknown`) per `open-weakpoints.md` #5 -- two real messages had
previously fallen back to `unknown` for these: "Θέλω να ακυρώσω το ραντεβού
μου" (cancel my appointment) and "Χρειάζομαι να κλείσω ραντεβού" (book an
appointment). Added matching templates to `answer_composition.py`'s
`_ACTION_TEMPLATES`.

## Result: mixed, not a clean win

Re-tested both original messages plus more:

| Message | action |
|---|---|
| "Θέλω να ακυρώσω το ραντεβού μου." (cancel) | `cancel` -- correct |
| "Χρειάζομαι να κλείσω ραντεβού για την Δευτέρα." (book) | `cancel` -- **wrong, should be `schedule`** |

`schedule` was never actually produced. The booking message got confidently
misclassified as `cancel` -- worse than before in one specific way: this
message used to safely fall back to `unknown` (leading to the safe
answer_type-based template); now it confidently tells the user "Για να
ακυρώσετε..." (to CANCEL...) when they were trying to book, not cancel.

**Likely cause:** `ACTIONS` is passed to the LLM as a bare
`", ".join(ACTIONS)` list, no definitions -- same shape `INTENTS` used to be
before `fix-002` added `INTENT_DEFINITIONS`, which fixed several real
misclassifications by teaching the general rule instead of leaving categories
to be inferred from the word alone. "cancel" and "schedule" are two
plausible-sounding action words for anything involving "ραντεβού"
(appointment); without a definition distinguishing "wants to remove an
existing booking" from "wants to create a new booking", the model doesn't
reliably tell them apart.

**Not yet fixed.** Flagging this rather than shipping it quietly -- `ACTIONS`
likely needs the same definitions treatment `INTENTS` got in `fix-002`,
not attempted yet.

## Bonus finding: a new wrong-purpose kb_match case

Both appointment messages also matched `kb_match` to "Απομάκρυνση ογκωδών
αντικειμένων με ραντεβού" (bulky-item removal, by appointment) purely because
`service` resolved to the bare, generic word "ραντεβού" (appointment) with no
indication of what the appointment was actually for -- and that's the only KB
title containing the word "ραντεβού". Different from the `fix-010` failure
mode (no shared generic *administrative* word here -- "ραντεβού" is a
legitimate content word, just meaningless on its own when the message itself
never says what the appointment is for). See `open-weakpoints.md` #9 for the
updated status -- this confirms the wrong-purpose-match problem does reach
`request_service` intent, not just complaints.
