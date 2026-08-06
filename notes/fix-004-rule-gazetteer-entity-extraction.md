# Fix 004: rule/gazetteer-based extraction for `date` and `document`/`service`

## Why

Raised directly: would entity extraction be more concrete and faster without an
LLM? Answer worked out to: yes, but only for the entity types that are actually
closed-vocabulary in this domain.

- `date` -- Greek has exactly 7 weekday names and a small set of relative-date
  phrases. No long tail to miss. Testing had already shown pure LLM variance
  here specifically: "Σάββατο" was missed in one message, "Δευτέρα" caught in
  another, same entity type, no real difference in difficulty -- a fixed list
  doesn't have that variance.
- `document`/`service` -- this chatbot only ever talks about Heraklion's real
  municipal services, a finite, already-enumerated set (167 titles in
  `data/heraklion_eservices.json`). In this domain these entity types
  effectively ARE the KB, so matching against it directly is both faster and
  more grounded than an LLM guessing a span.
- `location`/`other` stay LLM-only -- genuinely open-ended, no rule-based option.

## What was built

- `date_rules.py` (new) -- regex for absolute dates + fixed weekday/relative-phrase
  list. No model call.
- `gazetteer.py` (new) -- same technique v1's gazetteer.py already validated
  (char n-gram + word-overlap TF-IDF, 70/30 blend), rewritten fresh rather than
  imported so it's understandable without v1 as a reference. Matches the whole
  message against real KB titles, then extracts the entity SPAN as the longest
  contiguous run of the message's own words that also appear in the matched
  title (entities must stay real substrings of the message everywhere in this
  pipeline, same rule as always).
- `entity_extraction.py` (restructured) -- `extract_entities` now combines all
  three sources: dates + gazetteer service always run first (cheap,
  deterministic), then one LLM call for `location`/`other` plus `document`/
  `service` as a fallback when the gazetteer found nothing, with a hint listing
  what's already found so the LLM doesn't duplicate it.

## Bugs found during verification (not shipped as "done" on first pass)

Ran the combined function against the accumulated test set immediately after
building it, rather than assuming the design worked -- found three real issues:

1. **Punctuation leaking into spans.** "Πού βρίσκεται το δημαρχείο Ηρακλείου;"
   produced `{"text": "Ηρακλείου;", ...}` -- the trailing Greek semicolon got
   baked into the entity text. `find_service_entity` checked a punctuation-stripped
   version of each word for matching, but appended the *original* (unstripped)
   word to the span. Fixed: append the stripped version.

2. **Attractor-title false positive**, same example -- "Ηρακλείου" alone
   (a common proper noun appearing in many KB titles) cleared the match
   threshold and produced a near-meaningless one-word `service` entity, on top
   of the correct `location` entity for the same phrase. This is exactly the
   failure mode v1's gazetteer notes warned about, and it shipped anyway on the
   first pass despite the warning being copied into this file's own comments.
   Fixed: require the matched span to be 2+ words, not 1 -- a real service
   reference shares more than one content word with its KB title, a
   coincidental proper-noun overlap doesn't. Tradeoff: loses some genuine but
   weak single-word matches (e.g. bare "τέλη" for a fees question) -- accepted,
   since the LLM fallback still gets a chance at those.

3. **Overlapping duplicate entities across types.** "...πιστοποιητικό γέννησης
   για τον γιο μου..." produced *both* `{"γέννησης", "service"}` (a weak
   gazetteer fragment) and `{"πιστοποιητικό γέννησης", "document"}` (the fuller,
   correct LLM span) as two separate entities. The original duplicate check only
   compared exact text + exact type, so it missed this (different text,
   different type, same underlying thing). Fixed: `_merge_entity` now checks
   substring overlap in either direction regardless of type, and keeps whichever
   span is longer/more complete instead of keeping both.

## Evidence (same 10-message test, before fixes / after fixes)

| Message | Before fixes | After fixes |
|---|---|---|
| "δημαρχείο Ηρακλείου;" | `location` entity + spurious `"Ηρακλείου;"` service entity | just the correct `location` entity |
| "...γέννησης...Παρασκευή...δημαρχείο Ηρακλείου." | 4 entities incl. duplicate `"γέννησης"` fragment | clean 3 entities (date, document, location) |
| "Σάββατο" weekday recall | correct | correct (unaffected by fixes, confirms no regression) |
| "σύνδεση φυσικού αερίου" (not in KB) | correct via LLM fallback | correct via LLM fallback (unaffected, confirms fallback still works) |

No regressions found on any of the previously-correct messages.

## Honest limitations, not fixed by this pass

- **Speed win is smaller than expected.** The design still makes exactly one
  LLM call per message (for `location`/`other` coverage), so overall wall-clock
  time per message barely moved (~8-10s average before and after). The real,
  confirmed win from this rework is *determinism* on dates and *fewer
  KB-groundless false positives* on service/document, not raw speed. Worth
  correcting the framing from the earlier discussion, which implied a bigger
  latency win than what actually landed.
- **The fee/tax question-form gap is still open.** "Πρέπει να πληρώσω τα
  δημοτικά τέλη μέχρι πότε;" still returns zero entities -- the gazetteer's
  match on this phrasing doesn't clear the (now stricter, 2+ word) span
  requirement, and the LLM fallback doesn't independently recover it either.
  Still tracked in `open-weakpoints.md`.
- **Existing span-precision issues on `document`/`service` from the LLM path
  are unchanged** -- e.g. "κοινωνικό επίδομα" still comes back as the generic
  word "αίτηση" instead of the real service phrase. This rework didn't touch
  that failure mode since it happens on the LLM fallback path, not the
  gazetteer path.
