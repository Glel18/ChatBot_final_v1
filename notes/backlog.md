# Backlog

Side objectives and future ideas that came up while working on something else --
real and worth doing, but deliberately not right now, so they don't fragment
whatever's actively in progress. Pull an item out of here into its own
`fix-NNN-*.md` when it's actually picked up.

## Enrich the gazetteer with Expanded_Intent_Dataset_2.csv phrasings

`gazetteer.py` (built in `fix-004`) currently matches messages against 164 bare
KB titles only -- short, formal strings, no example phrasings. The dataset at
the repo root was updated to a clean, balanced version: 10,104 rows, 101
categories, 100-101 examples each (previously 147 categories ranging from 1 to
101 examples, with corrupted duplicate labels -- now fixed).

That's ~100 real conversational phrasings per service category, which could
plausibly improve TF-IDF matching beyond what bare titles give it -- worth
trying against known open issues like the "κοινωνικό επίδομα" span-precision
miss (`open-weakpoints.md`) and the fee/tax question-form recall gap (#1
there).

**Not a trivial swap.** The dataset's 101 categories and the KB's 164 titles
are not the same list -- e.g. `σύνδεση_φυσικού_αερίου` (gas connection) exists
as a labeled category in the dataset but has no corresponding title in
`data/heraklion_eservices.json` at all (confirmed while building `fix-006`).
Would need real reconciliation work: deciding how to map/merge the two
sources, handling categories with no KB equivalent, and re-testing for new
attractor-title-style false positives now that there's much more text in the
matching corpus.

**Decided to defer** (2026-08-05): `fix-006` (KB lookup) had just been built
and only lightly tested. Stacking a second, differently-scoped enrichment task
on top risked fragmenting focus before properly evaluating what was already
built. Nothing about waiting makes this harder later -- the dataset is stable.

**Update (2026-08-05, `ipiresies.pdf` cross-check):** the `σύνδεση_φυσικού_αερίου`
example above needs reframing, not removing. A human-audited PDF
(`ipiresies.pdf`, cross-referencing the municipality's real service catalog
against the intent database) independently confirms this and 20 other
services genuinely don't exist as a real service anywhere yet -- not just
missing from our specific KB scrape. No amount of gazetteer/matching
improvement, dataset enrichment included, can ever produce a correct match
for a service that doesn't exist yet. That fix has to happen upstream (the
service gets built and published, then re-crawled into
`data/heraklion_eservices.json`) -- it isn't a matching-algorithm problem for
this backlog item to solve. See the new "Confirmed not-yet-implemented
services" entry below for the full list. The rest of this item (the
still-implemented-but-poorly-matched cases) stands as originally written.

## Confirmed not-yet-implemented services -- checklist for when they're added

Cross-referenced `ipiresies.pdf`'s "no identical service exists on the site"
list (39 intents marked green in its initial database list) against our real
KB using `gazetteer.py` directly (not a separate ad-hoc comparison -- the
actual matcher the live pipeline uses). 21 of the 39 have zero KB match at
any confidence level, confirming they don't exist as a real, matchable
service in our system today, independent of the PDF's own manual judgment:

- Δελτία_Τύπου (press releases)
- άδεια_κολυμβητικής_δεξαμενής (swimming pool permit)
- άδεια_μικρής_κλίμακας (small-scale permit)
- αίτηση_εκταφής (exhumation request)
- αγωγοί_αποχέτευσης (sewer pipes)
- διακοπή_παροχής_ύδατος (water supply cutoff)
- διακοπή_υδροδότησης (water service cutoff)
- είσοδος_έξοδος (entry/exit [permit])
- εγγραφή_σημείου_υδροληψίας (water-intake-point registration)
- ενοικίαση_οστεοφυλακίου (ossuary rental)
- ενοικίαση_τάφου (grave rental)
- επανασύνδεση_παροχής (supply reconnection)
- επικοινωνία (contact)
- μείωση_τελών_λόγω_αναπηρίας (fee reduction for disability)
- μείωση_τιμολογίου (tariff reduction)
- μητρώο_αρρένων (male registry)
- παλαιότητα_1955 / παλαιότητα_1990 (building-age certificates, pre-1955/1990)
- στέγαστρο_οασα (bus shelter)
- σύνδεση_φυσικού_αερίου (gas connection -- the case already known from `fix-006` testing)
- χιλιομετρική_απόσταση (distance/mileage certificate)

**Purpose:** when the other team adds these as real services (and they get
re-crawled into the KB), this list is the checklist to confirm against --
re-run each through `gazetteer.find_kb_match` and expect a real hit once
it's actually been added, rather than guessing whether coverage improved.

**Also surfaced, worth flagging separately:** of the 39 PDF-flagged
"no-service" intents, 15 (not the 21 above) *did* return some match from our
gazetteer despite the PDF saying no matching service exists. On inspection,
most of these are wrong -- coincidental shared-word matches, the same
`open-weakpoints.md` #9 failure mode, not real coverage. E.g.
`μεταφορά_οστών` (transfer of remains) matched "Μετακίνηση...κάδων" (moving
garbage bins) purely via the shared word "μεταφορά" (transfer/moving);
`επέκταση_δικτύου_ύδρευσης` (water network expansion) matched "Βλάβες...
δημοτικού φωτισμού" (lighting network faults) via the shared word "δικτύου"
(network). Added to `open-weakpoints.md` #9 as additional real-world
evidence of that still-open problem -- these are new, concrete examples, not
resolved by `fix-010` (they don't share a generic *administrative* word, they
share a real but topically-unrelated content word, same residual failure
mode `fix-010` already flagged as unfixed).

## Ask-for-clarification retry loop for near-miss `no_kb_match` cases

Raised while testing `fix-008`'s `no_kb_match` fallback (currently: name what
we understood, point to the phone number). Question was whether that fallback
should instead ask the user to clarify and re-run their reply through the
pipeline.

Doesn't help uniformly -- `no_kb_match` covers two different situations that
look identical from the caller's side:

- **Genuine KB gap** (confirmed real, e.g. `σύνδεση φυσικού αερίου` isn't in
  `data/heraklion_eservices.json` at all, at any confidence level). The user
  was already completely clear; asking them to clarify would wrongly imply
  the problem was their phrasing when it's actually missing coverage on our
  end.
- **Near-miss** -- the gazetteer found something close that didn't clear
  `MIN_MATCH_SCORE`. Here a clarifying question genuinely could help, and
  could be targeted ("did you mean X?") rather than a blind "please rephrase."

**Worth doing, but scoped to the near-miss sub-case specifically, not a
drop-in replacement for the phone-number fallback across the board.** Two real
prerequisites, neither trivial:

1. `find_kb_match` currently only returns a title above threshold or `None` --
   it discards the best below-threshold candidate. Would need to expose that
   runner-up (score included) so the clarification can name it.
2. The "ask, then re-run the reply" loop needs conversation state that doesn't
   exist anywhere in this pipeline right now -- `run.py` and everything under
   it treats each message as fully independent. Deciding how a follow-up
   combines with the original message, and what happens if the follow-up is
   *also* ambiguous, is real design work, not a small tweak.

**Decided to defer** (2026-08-05): explicitly a "for later, if needed" item,
not picked up now.

## Semantic embeddings for gazetteer matching (using the existing dimos-intent-model)

Raised while investigating `open-weakpoints.md` #9 (`kb_match` producing
wrong-purpose matches). `fix-010` fixed the sub-case caused by shared generic
administrative words, but the remaining failure mode -- real content-word
overlap pointing to a topically-right, purpose-wrong title (e.g. "water bill"
matching a payment page when the user is disputing a charge, not paying) --
is a lexical-matching ceiling, not a tunable parameter. TF-IDF (char n-grams
+ word overlap) structurally cannot distinguish "same topic, different
purpose" -- it only measures shared characters/words, not meaning.

**Checked whether an embedding-based approach is even possible here first**
(no internet access to either HuggingFace or Ollama's registry, confirmed by
directly testing both -- so downloading a fresh embedding model is off the
table). But `transformers` and `torch` are already installed, and
`dimos-intent-model/` at the repo root is a real, already-downloaded Greek
`BertForSequenceClassification` model, fine-tuned on the same
147-category municipal-service vocabulary as `Expanded_Intent_Dataset_2.csv`.
Its encoder's hidden states could be extracted as embeddings (drop the
classification head, mean-pool or use the [CLS] token) -- a known technique,
needs zero downloads since the weights are already local.

**Not a guaranteed win.** This model was fine-tuned for discrete
classification, not for general-purpose semantic similarity -- its embeddings
might be good (and plausibly *better* than a generic model here, since it's
already domain-specific) but that's not the same guarantee a model
purpose-trained via a similarity objective would give. Would need real
testing against the known good/bad cases before trusting it, same as
everything else in this project. Also inherits the same "categories don't
map 1:1 to KB titles" complication already flagged in the gazetteer-enrichment
backlog item above.

**Decided to defer** (2026-08-05): the free, no-dependency fix (`fix-010`)
was tried first and resolved part of the problem. This is the natural next
escalation if the remaining wrong-purpose-match problem keeps showing up on
`question`/`request_service` messages (not just the currently-masked
complaint cases) -- not picked up now.

**Update (`fix-011` testing, still 2026-08-05):** the trigger condition above
already happened -- confirmed a wrong-purpose match on `request_service`
("ακυρώσω/κλείσω ραντεβού" both matched a bulky-item-removal service purely
via the bare word "ραντεβού"). Still not escalating to this yet, though --
that specific case is about `service` being too vague/generic to signal
purpose at all, which embeddings wouldn't obviously fix either (a vague query
is vague regardless of matching technique). Keeping this deferred until a
case shows up that's specifically about topic-vs-purpose confusion (the
water-bill/bin pattern) on a non-complaint message, which is the failure mode
this was actually meant to address.

**Update (`fix-012`, still 2026-08-05):** much stronger evidence for exactly
that pattern now exists -- 15 topic-vs-purpose-confusion matches found in one
pass (`μεταφορά_οστών` -> bin relocation, `επέκταση_δικτύου_ύδρευσης` ->
lighting faults, etc., see `open-weakpoints.md` #9). Important caveat before
treating this as the trigger fully met, though: those 15 were found by
calling `find_kb_match` directly on bare intent-name strings, not by running
a real message through the full pipeline and confirming the intent resolves
to `question`/`request_service` end-to-end. Strong evidence at the gazetteer
level; not yet a confirmed end-to-end case. Still deferred, but this is now
the best-evidenced escalation trigger in this file if someone wants to
actually pick it up.

**Update (`fix-013`, 2026-08-06): trigger substantially defused, not fully
closed.** A cheaper fix than embeddings -- a 2-shared-content-word-stem gate
on `best_match`, the same technique `find_service_entity` already used since
`fix-004` -- resolved 14 of the 15 cases that motivated this item, confirmed
end-to-end through the real pipeline (the specific gap flagged above as
"not yet a confirmed end-to-end case" is now closed). One case remains
unfixed and is the kind embeddings were originally proposed for: cemetery
cleaning fees still matches a general lighting-and-cleaning fee title on 2
genuine shared content words, a real same-topic-different-scope confusion
that word overlap structurally can't resolve (see `fix-013` for detail).
Still deferred -- one residual instance, not a live pattern, doesn't justify
the model-swap risk this item already flags as unproven. Revisit if more
cases of this specific shape (2+ real shared words, still wrong) turn up.

## Domain-filtered retrieval for the gazetteer

Raised while reading v1's original design document
(`structured-intent-design.md`, not in this repo -- the user's copy of the
plan that guided v1's build). Its Layer 3 proposes filtering the KB to a
resolved domain/category bucket *before* running TF-IDF matching, rather than
comparing every message against all 164 titles every time the way
`gazetteer.py` does now.

**Why this is the most relevant idea in that document for v2 specifically:**
it would structurally prevent the whole class of bug `fix-009`/`fix-010`/
`fix-011` have been fighting after the fact. "Άδεια εκσκαφής" (excavation
permit) would never even be compared against "Άδεια Πολιτικού Γάμου για
Αλλοδαπούς" (foreign marriage license) if marriage-related titles were
filtered out of the candidate pool before matching started -- rather than us
noticing the collision afterward and patching the scoring (stripping shared
words, requiring longer spans, bypassing certain intents). Shrinking the
candidate pool is a different kind of fix than tuning the scoring formula
further, and it's the one the current approach structurally can't reach.

**Not implemented in v1's actual code, worth noting.** `gazetteer.py`'s v1
predecessor explicitly skipped this ("We're skipping BERT entirely, and this
KB is only ~164 real titles -- small enough that matching against all of
them directly is cheap") -- so this is aspirational from that document, not
something already proven out and just waiting to be ported.

**Real prerequisites, neither trivial:**
1. The KB's `category` field (18 messy, mixed English/transliterated-Greek
   values, per that design doc's own diagnosis) is never used anywhere in
   v2's `gazetteer.py` today -- only `title`/`url` are. Would need
   normalizing into a clean domain taxonomy first.
2. v2 has no domain-resolution step at all. Would need to decide how a
   message's domain gets resolved before gazetteer matching even runs --
   plausibly connects to the gazetteer-enrichment backlog item above, since
   `Expanded_Intent_Dataset_2.csv`'s 101 categories are a candidate domain
   taxonomy already sitting there.

**Decided to defer** (2026-08-05): real feature work, not a quick patch --
needs the domain-resolution step built first, which doesn't exist anywhere
in the current pipeline.

## Clause-splitter for compound/multi-intent messages -- next thing to build after handoff

**Status (2026-08-06): promoted to top of the backlog.** Explicitly flagged
as the next thing to pick up once the pipeline is handed off, ahead of
everything else in this file -- not just a deferred idea anymore.


Also from v1's `structured-intent-design.md` (Layer 1, point 5): a pre-pass
that splits a message on conjunctions ("και"/"ή") and punctuation before
intent scoring -- but only when both halves independently resolve to a
*different* intent, so it doesn't over-split compound noun phrases that
merely contain "and" (e.g. "πιστοποιητικό γέννησης και θανάτου" is one
service phrase, not two intents).

**Directly fills a gap already tracked**, not a new discovery:
`open-weakpoints.md` #6 -- compound messages currently either blend two
sub-requests into one inconsistent record ("action" from clause 1,
"answer_type" from clause 2), or in one observed case fully collapsed to a
single intent and silently dropped a complaint signal entirely. This was
accepted as a known, deliberate simplification when the pipeline was first
built, not something we'd tried and failed to fix.

**Not a trivial port, because v2's intent resolution isn't rule-based.** v1's
design assumes a scored keyword rule engine that can cheaply check "does each
half score a different intent" without any model call. v2 always resolves
intent via one LLM call (`structured_intent.py`) -- there's no cheap
rule-only signal to decide *whether* a message needs splitting before paying
for it. Naively splitting and running the full LLM call on each half would
double latency for every compound message, not just the minority that
actually need it. Would need either a cheap rule-only pre-check (e.g.
conjunction detection plus a lightweight per-clause keyword guess, closer to
v1's actual approach) to decide when splitting is worth the extra call, or
accept the latency cost outright.

**Decided to defer** (2026-08-05): needs real design work on the "when to
split" question before it's a small change, not just a port of v1's logic.

**No longer just deferred (2026-08-06):** raised again post-handoff-prep as
the clearest remaining gap in the pipeline -- compound messages ("apply for
X and also tell me the cost") still blend or drop a sub-request, and that's
now the most visible known limitation left. The open design question is
unchanged from above (cheap rule-only pre-check to decide *when* a message
needs splitting, since v2 has no free rule-based intent signal to check
that with before paying for an LLM call) -- picking this up should start by
answering that, not by writing the splitter itself.

**Relevant new tool for that question (2026-08-06):** `eval_log.jsonl` now
carries a `metrics` block per message (`ollama_client.py`/`run.py`) --
`total_pipeline_ms` and per-LLM-call timings, broken out by which step each
call was for. The "double latency for every compound message" concern above
no longer has to be reasoned about in the abstract -- real per-call
timings from a batch of real messages (`run_full_eval.py`) can show the
actual current cost of one `structured_intent_llm` call before deciding
whether doubling it (naive splitting) is acceptable or whether the
rule-only pre-check is worth building first.

## Concurrent classifier voting for intent, with disagreement as a monitored signal

Also from `structured-intent-design.md` (Layer 2) -- distinct from the
embeddings idea above (that one's about entity/service matching precision,
this one's about intent-classification reliability). The idea: run a
calibrated classifier (e.g. a retrained `dimos-intent-model`) alongside
intent resolution, always, not as a fallback -- resolve immediately when the
rule/LLM result and the classifier agree, escalate only on disagreement. The
sharper part: agreement cases become free auto-labeled training data over
time (a "data flywheel"), and disagreement *rate* becomes the thing you
monitor, not just an aggregate accuracy number.

**Genuinely good pattern, but the furthest out of everything in this file.**
It only pays off once there's a reason to retrain a classifier at all --
same threshold already agreed on elsewhere in this project (fine-tuning
becomes worth it once the JSONL eval log has real volume, not before -- see
the earlier fine-tuning discussion in this project's history). Also inherits
the same calibration caveat as the embeddings idea: `dimos-intent-model` was
trained on the pre-cleanup, corrupted label set (see `structured-intent-
design.md` Section 1 -- confirmed independently, its `id2label["0"]` really
is `"nan"`), so its confidence scores likely don't mean what they'd look
like even if reused as-is.

**Decided to defer** (2026-08-05): noted per the design document review, not
picked up now -- furthest from anything currently evidenced as a live
problem in v2.

## ~~Rule-based fast path for intent/answer_type~~ -- picked up, see `fix-016`

Picked up and shipped 2026-08-06: `pipeline/intent_rules.py`, wired into
`structured_intent.py` as a pre-check before `structured_intent_llm`.
23/40 messages hit the fast path in testing, ~55-65% latency reduction on
those, reproduced across two full batch runs. See `fix-016` for the full
design and evidence, including what it does and doesn't fix relative to
`open-weakpoints.md` #3/#5/#6/#7/#8.

## ~~Formal schema/consistency validator~~ -- picked up, see `fix-015`

Picked up and shipped 2026-08-06 (built first, ahead of the fast path
above, since the fast path needed something to validate its candidate
records against before either existed): `pipeline/validator.py`. The
hard-vs-soft question this item left open was resolved as a deliberate
split, not one answer -- soft/logged on the existing LLM path, hard (but
caught one frame up, never surfaced) on the new fast path's candidate
records. See `fix-015` for the full design and evidence.
