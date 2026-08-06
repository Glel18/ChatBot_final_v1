# Fix 013: require 2+ shared content words in `Gazetteer.best_match`, not just score

## Why

`open-weakpoints.md` #9, still open after `fix-010`: `kb_match` -- the field
every composed answer is grounded on -- kept producing confidently
wrong-purpose matches on `question`/`request_service` messages, not just the
complaint cases `fix-009` had already routed around. Real examples from
testing: a bare "ραντεβού" (appointment) matched a bulky-item-removal
service purely on that one uninformative word (`fix-011`); the `ipiresies.pdf`
audit (`fix-012`) found 15 more of the same shape by running confirmed
non-existent service names through `find_kb_match` directly -- e.g.
`μεταφορά_οστών` (transfer of remains) matched "Μετακίνηση...κάδων" (moving
garbage bins) via the shared word "μεταφορά"; `επέκταση_δικτύου_ύδρευσης`
(water network expansion) matched "Βλάβες...δημοτικού φωτισμού" (lighting
network faults) via "δικτύου".

## Diagnosis

The root cause was a real asymmetry between two functions that both sit on
top of the same TF-IDF matching:

- `find_service_entity` (built in `fix-004`) has required 2+ shared
  significant words between message and title since the day it was written --
  a single shared word, often a coincidental proper noun or unrelated content
  word, was already known not to be enough evidence of a real match.
- `best_match` -- which `find_kb_match` calls directly, and which is what
  actually produces the live `kb_match` field used in every composed answer --
  never had that protection. It only checked the TF-IDF score against
  `MIN_MATCH_SCORE`. Every wrong-purpose match found in `fix-009`/`fix-011`/
  `fix-012` testing went through this exact path, unprotected.

Also re-confirmed before implementing: a stricter score threshold can't fix
this on its own (`tried-and-failed.md`, from `fix-010`'s investigation) --
bad and good matches are interleaved across the whole score range, no cutoff
keeps both good matches while dropping every bad one.

## Fix

Added the same word-overlap requirement `find_service_entity` already had to
`best_match` itself, so every caller (including `find_kb_match`, and
therefore every composed answer) gets the protection, not just the entity
extraction path.

First attempt used exact-word-string overlap and immediately regressed:
tested against a suite of known-good matches and found 2 broke --
"δημοτικός φωτισμός" (street lighting, nominative case in the KB title) no
longer matched "δημοτικού φωτισμού" (genitive case, as it naturally appears
inflected in a real sentence) because Greek grammatical case changes the
exact string even though the char n-gram scorer (which already handles this
correctly) considers them clearly the same word. Caught by testing against
the full known-good set before trusting the change, not by reasoning about
it -- consistent with how every fix in this project has been validated.

Fixed by comparing word STEMS instead of exact strings: first
`_WORD_STEM_LENGTH = 5` characters of each word ≥ `_MIN_SPAN_WORD_LENGTH`
(4) characters, on both the query and the matched title's already-stripped
text (`self.titles_for_matching`, stored as an instance attribute instead of
a throwaway local specifically so `best_match` could reuse it). 5 was chosen
empirically: long enough that unrelated words don't collide (e.g.
"καδος"/bin vs "καδων"/bins differ at character 4, so the bin-relocation
false positive stays correctly rejected), short enough to absorb the
1-3 character case endings Greek nouns/adjectives actually use.

## Evidence

**Direct `best_match`/`find_kb_match` calls**, full known good/bad suite,
13/13 correct after the stem-based fix:

| Query | Expected | Result |
|---|---|---|
| residence certificate | match | correct match |
| street lighting fault (nominative phrasing) | match | correct match |
| street lighting fault (genitive phrasing, the regression case) | match | correct match (fixed) |
| bin relocation (2 phrasings) | match | both correct |
| excavation permit | no match | correctly rejected |
| passport issuance | no match | correctly rejected |
| water bill dispute | no match | correctly rejected |
| bare "ραντεβού" | no match | correctly rejected |
| recycling bin (question phrasing) | match | correct match |
| gas connection | no match (genuine KB gap, not a matching bug) | correctly rejected |
| business license | match | correct match |
| water network expansion | no match | correctly rejected |
| transfer of remains | no match | correctly rejected |

**`ipiresies.pdf` audit re-test**: re-ran all 15 previously-wrong matches
found in `fix-012` through the fixed matcher. **14 of 15 now correctly
rejected** (`kb_match: None`). One residual case:
`τέλη καθαριότητας κοιμητηρίων` (cemetery cleaning fees) still matches
"ΤΑΠ - Τέλη Φωτισμού και Καθαριότητας" (lighting-and-cleaning fee, score
0.658) -- this one is the most defensible of the 15, since it shares 2
genuine content words (τέλη, καθαριότητας), not a coincidental or
generic-word overlap. See "What's not fixed" below.

**End-to-end pipeline confirmation** (2026-08-06): re-ran 6 real Greek
messages through the actual `resolve_structured_intent` pipeline (real LLM
calls resolving `service`, not hand-picked query strings feeding
`find_kb_match` directly):

| Message (topic) | Intent | `kb_match` |
|---|---|---|
| excavation permit | request_service | `None` -- correct |
| passport issuance cost | question | `None` -- correct |
| water bill, wrong data (complaint) | complaint | `None` -- correct |
| cancel appointment (bare "ραντεβού") | request_service | `None` -- correct |
| residence certificate for the bank | request_service | matched correctly (0.735) |
| street lighting out for a week (complaint) | complaint | matched correctly (0.374) -- lighting-faults title, the RIGHT service |

Zero bad matches across the batch. Notably the street-lighting complaint now
gets the genuinely correct match (previously this exact failure mode is what
`fix-009` had to route around for complaints generally) -- though since
`fix-009` still never surfaces `kb_match` in a composed answer for
`complaint` intent regardless of whether it's right, this doesn't yet change
what the user sees for that message; it just confirms the underlying
gazetteer call itself is no longer poisoning that field.

## What's not fixed, and why that's OK for now

One residual case out of the full evidence base (1 of 15 PDF-audit cases,
0 of 13 direct test cases): two real shared content words can still describe
a *different purpose* for the same topic. "Cemetery cleaning fees" shares
"τέλη" and "καθαριότητας" with a title that's genuinely about fees and
cleaning -- just a different scope (general municipal lighting/cleaning tax,
not cemetery-specific). Word overlap, however strict, measures topic
overlap, not purpose match -- distinguishing "report damage" from "request
relocation" (or here, "this specific fee" from "a related general fee")
needs semantic understanding of what the words mean together, not just
which words are present. This is exactly the ceiling `backlog.md`'s
semantic-embeddings entry already anticipated. Not chasing further now:
the remaining case is a single instance, is the most defensible of the
batch it came from, and going further trades simple/explainable
(word-stem overlap) for a much bigger, unvalidated change (a different
model entirely) for one edge case.

## Status update

`open-weakpoints.md` #9 is now considered largely resolved: 14 of the 15
concrete wrong-purpose-match examples found across `fix-009`/`fix-011`/
`fix-012` testing are fixed, confirmed both in isolation and end-to-end
through the real pipeline. One documented residual case remains
(cemetery cleaning fees), tracked as a known limitation rather than an
open bug, since it reflects a genuine ceiling of word-overlap matching
rather than an unaddressed instance of the original problem.
