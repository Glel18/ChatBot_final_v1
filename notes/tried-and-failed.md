# Tried and failed

Approaches actually attempted (not just considered) that didn't hold up once
tested, and got reverted or rejected. Different from `open-weakpoints.md`
(known issues in what's currently shipped) and `backlog.md` (ideas deferred,
not yet tried) -- this is specifically the "we built/proposed this, tested it,
it was wrong" record, so that reasoning isn't lost once the code moves on.

## kb_match takes priority over intent for complaints (fix-008 -> fix-009)

**Tried:** in the original answer-composition branching, `kb_match` was
checked before any intent-specific handling -- so a complaint with a
confident KB match would get the KB-grounded template instead of the generic
acknowledgment.

**Why it looked right at first:** the first live test ("broken street
lighting") matched straight to the real fault-report page -- a genuinely
better answer than a generic phone number.

**Why it failed:** tested against 6 real complaints. Of the 3 that produced a
`kb_match`, only 1 was actually correct. The other 2 were topically adjacent
but functionally wrong -- a billing *dispute* matched to a "pay your bill
online" page, a broken-bin *damage report* matched to a "relocate your bin"
page. Confidently pointing someone to the wrong process is worse than the
generic fallback.

**What changed:** `fix-009` -- complaints now always use the acknowledgment
template, `kb_match` is never checked for them.

## Raising MIN_MATCH_SCORE to filter out bad kb_match hits

**Tried (analysis only, not shipped):** after finding wrong-purpose matches
outside complaints too (question/request_service messages -- "excavation
permit" matched to "civil marriage license for foreigners", 0.317; "passport
issuance cost" matched to "municipal tax clearance issuance", 0.319), checked
whether a stricter `MIN_MATCH_SCORE` threshold in `gazetteer.py` would filter
these out while keeping the genuinely good matches.

**Why it failed:** sorted every match seen in testing by score, good and bad
together:

| score | match | good/bad |
|---|---|---|
| 0.317 | excavation permit -> foreign marriage license | bad |
| 0.319 | passport issuance -> tax clearance issuance | bad |
| 0.324 | water bill dispute -> pay bill online | bad |
| 0.373 | street lighting fault -> lighting fault reports | **good** |
| 0.420 | broken recycling bin -> relocate your bin | bad |
| 0.774 | residence certificate -> residence certificate | **good** |

There's no threshold that keeps both good matches and drops all the bad
ones -- the 0.420 bad match sits *above* the 0.373 good one. Score (lexical
closeness) doesn't track functional correctness (same real-world service).
This isn't a calibration problem fixable by moving one number.

**What changed:** nothing shipped from this -- flagged as a broader,
unresolved reliability question about the gazetteer's matching approach at
low-to-mid confidence, not scoped to complaints specifically. Needs a
decision on how far to trust `kb_match` at all before composing an answer
from it, independent of intent.

## Hoping some PDF-flagged "no service" intents might already work anyway

**Tried:** `ipiresies.pdf` (a human audit of the municipality's real service
catalog) marks 39 intents as having no identical service on the site at all.
Since our pipeline doesn't depend on the old intent classifier's training
coverage -- `gazetteer.py` matches directly against real KB titles, not
against trained categories -- checked whether any of these 39 might already
have a real, working match in our system that the classifier's training data
simply never captured.

**Why it looked worth trying:** already had one concrete example of exactly
this happening -- "Άδεια Πολιτικού Γάμου για Αλλοδαπούς" (foreign marriage
license) is marked as having no trained intent in the PDF's later services
list, yet it's a real KB title our gazetteer already matches perfectly (it's
the exact title `fix-011`'s excavation-permit test wrongly landed on). So it
seemed plausible some of the 39 "no service at all" intents were in the same
boat -- covered in practice, just never in the classifier's training set.

**Why it (mostly) failed:** cross-checked all 39 directly through
`find_kb_match` (the real matcher, not a separate comparison). 21 returned
nothing at all -- confirmed genuine gaps, now the `backlog.md` checklist. The
other 15 *did* return a match, but on inspection most are wrong: coincidental
shared-word matches, not real coverage. `μεταφορά_οστών` (transfer of
remains) matched a garbage-bin-relocation service via the shared word
"μεταφορά"; `επέκταση_δικτύου_ύδρευσης` (water network expansion) matched a
*lighting*-fault-report page via the shared word "δικτύου". So the
hypothesis -- "maybe our system already quietly covers some of these" --
mostly didn't hold. It surfaced more of the same known problem instead of
finding hidden coverage.

**What changed:** nothing shipped from the hypothesis itself. The 21 real
gaps became a checklist in `backlog.md`; the 15 wrong matches became new
evidence added to `open-weakpoints.md` #9 (still open, not fixed) -- the
largest batch of confirmed examples of that failure mode so far.
