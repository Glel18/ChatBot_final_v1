# Fix 009: complaints never use `kb_match`, even when one exists

## What happened

`fix-008` checked `kb_match` before any intent-based branching. First live
test ("Δεν λειτουργεί ο δημοτικός φωτισμός...") produced a genuinely good
result -- matched straight to the real street-lighting fault-report page. Read
as evidence the kb_match-first order was the right call, and said so.

Asked directly whether that was real evidence or a lucky single case. It was
lucky.

## Testing

Ran 6 real complaint messages through the full pipeline, spanning topics
likely to have a KB match and topics unlikely to:

| Complaint | kb_match | Verdict |
|---|---|---|
| "no response in 2 weeks" | `None` | n/a (no service resolved) |
| "wrong water bill" | "Ηλεκτρονική Εξόφληση Λογαριασμού ΔΕΥΑΗ" (pay bill online), score 0.32 | **wrong purpose** -- they're disputing a charge, not asking to pay |
| "broken street lighting" | "Βλάβες του δικτύου δημοτικού φωτισμού" (fault reports), score 0.37 | correct |
| "water leak on a street" | `None` | n/a |
| "broken recycling bin" | "Μετακίνηση...κάδων" (relocate your bin), score 0.42 | **wrong purpose** -- they're reporting damage, not asking to move a bin |
| "staff didn't help me" | `None` | n/a |

Of the 3 complaints that actually produced a `kb_match`, only 1 was right.
The other 2 were topically adjacent (same general subject) but functionally
wrong -- confidently pointing someone with a billing dispute to a payment
page, and someone reporting a broken bin to a bin-relocation page. That's
worse than the generic fallback: it looks authoritative while steering the
user toward the wrong process.

Also notable: score doesn't separate good from bad here. The *correct* match
(lighting, 0.37) scored *lower* than one of the *wrong* ones (bin, 0.42). So
this isn't fixable by raising `MIN_MATCH_SCORE` for complaints -- lexical
closeness to the complaint text doesn't track functional relevance to what a
complaint actually needs (reporting/routing, not payment/relocation/etc.).

## Fix

In `compose_answer`, `intent == "complaint"` is now checked FIRST, before
`kb_match` -- complaints always get the acknowledgment + phone-number
template, full stop, regardless of whether a KB match exists. Reverses the
precedence `fix-008` shipped with.

## Evidence

Re-verified all 3 previously-mismatched complaint cases (synthetic records
matching the exact real outputs from testing) now route to
`complaint_acknowledgment` regardless of their `kb_match`. Confirmed a
non-complaint case with a `kb_match` is unaffected -- still routes to
`kb_match` as before, so this change is scoped to complaints only.

## Open question this doesn't answer

Never rigorously tested whether `question`/`request_service` intents have the
same wrong-purpose-match problem when `kb_match` fires. Complaints got tested
because that's what came up first, not because they're uniquely at risk --
worth keeping in mind if a similar pattern shows up there.
