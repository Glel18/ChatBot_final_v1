# Fix 006: wire up step 4 (service / KB lookup)

## What

Pipeline step 4 from the original design ("Service / KB lookup") was
half-built: `gazetteer.py` already matched messages against real KB titles
internally for entity extraction, but the matched record (title + URL) was
never surfaced in the final output anywhere.

## Fix

- `Gazetteer.best_match` now returns the full record
  (`{"title", "url", "score"}`) instead of just `(title, score)`.
  `find_service_entity` updated to match.
- New `find_kb_match(query)` in `gazetteer.py` -- same underlying lookup,
  public, for use outside entity extraction.
- `structured_intent.py`'s `_normalize` now calls `find_kb_match(service)`
  using the already-resolved, `fix-003`-validated `service` field (per the
  original pipeline design: "seeded by the already-resolved service field,
  not a fresh full-text search"), and adds the result as a new `kb_match`
  field on every record. `None` if `service` is `None` -- nothing to seed
  the search with, and matching the raw message instead would re-invite the
  attractor-title false positives `find_service_entity` already had to
  guard against in `fix-004`.

## Evidence

- `"βεβαίωση μόνιμης κατοικίας"` (a real, correct `service` value from
  testing) -> matched `"Βεβαίωση Μόνιμης Κατοικίας Δημότη Ηρακλείου"` with a
  real URL, score 0.77.
- `"σύνδεση φυσικού αερίου"` -> `null`. Confirmed genuine (not a threshold
  problem): this KB file has no gas-connection title at all.
- `"άδεια λειτουργίας καταστήματος"` -> `null`. Also confirmed genuine: the
  KB has specific operating-license titles (music schools, preschools,
  market days) but no generic retail/store operating license.
- End-to-end through `resolve_structured_intent`: a real service message
  produced the full `kb_match` object correctly; "Γεια σας" (no service)
  correctly produced `kb_match: null` with no lookup attempted.
- Bonus, unplanned: the residence-certificate test message ("...μέχρι
  αύριο.") now also correctly catches `αύριο` as a `date` entity, which it
  had missed before `fix-004` -- confirms that fix holds on a message we
  hadn't specifically re-tested since.

## What this doesn't do yet

`kb_match` is only ever populated when `service` is a real, validated
string. Messages where `service` stayed `None` (a large fraction of
`question`/`complaint`-intent messages, by design) never get a KB lookup at
all, even if the message is clearly about a real service. That's expected
given the current design (step 4 seeded by step 3's `service` field, not the
raw message) -- not a bug, just the current boundary of what's built. Step 5
(answer composition) still doesn't exist -- `kb_match` is data available for
that step to eventually use, not itself an answer.
