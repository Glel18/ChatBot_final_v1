"""
gazetteer.py

Rule/lookup-based alternative to LLM extraction for `service`/`document`
entities: matches the message against real KB service titles instead of
asking a model to guess a span. Same fuzzy-matching technique v1 already
validated (char n-grams blended with whole-word overlap over TF-IDF),
written fresh here rather than imported, so this file is understandable
on its own without needing v1 as a reference.

Why this fits `document`/`service` specifically, unlike `location`/`other`:
this chatbot only ever talks about Heraklion's real municipal services,
and that's a finite, already-enumerated list (167 real KB titles) -- in
this domain, `document`/`service` names effectively ARE the KB. Matching
against it directly is both faster (no network call, sub-millisecond) and
more precise than an LLM guessing a span: testing had the LLM invent
values with no relationship to the input at all (English translations,
transliterations -- see notes/fix-003-service-field-guardrail.md). This
approach can't produce that failure by construction, since every match
traces back to a real KB title.
"""

import json
import re
import unicodedata
from pathlib import Path

from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity

KB_PATH = Path(__file__).resolve().parent.parent / "data" / "heraklion_eservices.json"

# "Ο ΛΟΓΑΡΙΑΣΜΟΣ ΜΟΥ" (My Account) is a site-navigation link in the raw KB
# dump, not a real municipal service -- v1 hit this exact false positive
# and excluded it; carrying that fix forward here instead of rediscovering
# it the hard way.
EXCLUDED_TITLES = {"Ο ΛΟΓΑΡΙΑΣΜΟΣ ΜΟΥ", ""}

# Below this score, report no confident match rather than guess -- callers
# fall back to the LLM in that case. v1 spent real iteration tuning this
# exact kind of threshold (its notes describe "attractor" titles: generic
# words that score confidently against an unrelated title purely because
# they're statistically rare elsewhere in the corpus). Treat this number
# as a starting point, not a final answer -- expect it to need adjustment
# once tested against more real messages.
MIN_MATCH_SCORE = 0.30

# Char n-grams tolerate Greek inflection (endings changing with case/number
# still share substrings); word-level overlap rewards matching real content
# words, which char n-grams alone under-weight. Blended rather than used
# alone -- word-overlap alone would let one shared generic word on a short
# title outscore a real multi-root match that's merely differently
# inflected. Same 70/30 split v1 validated.
CHAR_WEIGHT = 0.7
WORD_WEIGHT = 0.3

# Only words this long or longer count when extracting the entity SPAN
# from a matched title (see find_service_entity). Filters out common short
# Greek function words (για, το, της, και, με, ...) that could otherwise
# produce a meaningless one-word "match" between message and title.
_MIN_SPAN_WORD_LENGTH = 4

# How many leading characters of a word count toward the word-overlap check
# in best_match (fix-013). A cheap stand-in for real stemming: Greek
# inflection changes suffixes (case/number endings), not prefixes, so
# comparing first-N-characters instead of whole words tolerates that --
# "φωτισμός" (nominative) and "φωτισμού" (genitive) share the first 5
# characters even though they're different exact strings. First attempt at
# this used exact word matching and broke two known-good matches
# ("δημοτικός φωτισμός" / "δημοτικού φωτισμού", "μετακίνηση" cases) purely
# because of grammatical case, not because the match was actually wrong --
# caught by testing against the full known-good set before trusting it, not
# by reasoning alone. 5 chosen empirically: long enough that unrelated
# words don't collide (e.g. "καδος"/bin vs "καδων"/bins differs by
# character 4, so the recycling-bin false-positive case stays correctly
# rejected), short enough to absorb common 1-3 character case endings.
_WORD_STEM_LENGTH = 5

# Stems (not whole words, to catch inflected forms like αδειας/αδειων/αδειες)
# of generic bureaucratic-process vocabulary -- computed empirically from
# real word frequency across all 167 KB titles, not guessed. These are the
# 6 most common content-length words in the whole KB: χορηγηση (granting,
# 25 titles), αιτηση (application, 20), αδειας (permit, 15), εκδοση
# (issuance, 9), βεβαιωση (certificate, 9), δηλωση (declaration, 8).
#
# fix-010: testing found kb_match confidently matching completely unrelated
# services purely because they shared one of these words -- "άδεια
# εκσκαφής" (excavation PERMIT) matched "Άδεια Πολιτικού Γάμου για
# Αλλοδαπούς" (marriage LICENSE for foreigners), sharing nothing but
# "άδεια". These words describe the bureaucratic PROCESS (granting,
# applying, issuing), not WHAT the service is about -- stripping them
# forces matching to rely on the actual distinguishing content word
# (εκσκαφής vs γάμου), which is what should decide a match, not how
# common the paperwork verb is.
_GENERIC_ADMIN_STEMS = ("χορηγ", "αιτησ", "αιτημ", "αδει", "εκδο", "βεβαιω", "δηλωσ")


def normalize(text: str) -> str:
    """Accent- and case-insensitive form, for matching only."""
    decomposed = unicodedata.normalize("NFD", text)
    without_accents = "".join(c for c in decomposed if unicodedata.category(c) != "Mn")
    return without_accents.lower()


def _strip_generic_terms(normalized_text: str) -> str:
    """
    Drops words matching a generic-administrative-term stem from an
    already-normalized string, for MATCHING/SCORING purposes only. Used
    on both the KB titles (once, at index build time) and every query (in
    best_match) -- both sides need the same stripping applied, or the
    comparison isn't apples-to-apples.

    Deliberately does NOT touch find_service_entity's span extraction,
    which still needs the full, unstripped title to find real spans in
    the message -- stripping generic words only affects which title gets
    picked as the match, not what text gets returned as an entity once
    one is picked.

    A query that's entirely generic words (e.g. just "άδεια" alone) ends
    up as an empty string here, which correctly produces zero similarity
    to everything -- there's no real content to match on, so "no match"
    is the right outcome, not a bug to special-case around.
    """
    words = normalized_text.split()
    kept = [w for w in words if not any(w.startswith(stem) for stem in _GENERIC_ADMIN_STEMS)]
    return " ".join(kept)


class Gazetteer:
    """
    Loads the real KB once and builds two TF-IDF indexes over its titles.
    Expensive-ish to construct (loads + vectorizes 167 titles), so this is
    built once at module import time below, not per-message.
    """

    def __init__(self, kb_path: Path = KB_PATH):
        with kb_path.open(encoding="utf-8") as f:
            kb = json.load(f)
        self.records = [r for r in kb if r["title"] not in EXCLUDED_TITLES]
        # Two versions of each title: the full normalized text (kept only
        # for reference) and a generic-term-stripped version, which is what
        # actually gets vectorized -- see _strip_generic_terms. Kept as an
        # attribute (not a throwaway local) so best_match can also use it
        # for the word-overlap check below, on the exact same stripped text
        # the score was computed from.
        self.titles_for_matching = [_strip_generic_terms(normalize(r["title"])) for r in self.records]

        self.char_vectorizer = TfidfVectorizer(analyzer="char_wb", ngram_range=(3, 5))
        self.char_matrix = self.char_vectorizer.fit_transform(self.titles_for_matching)
        self.word_vectorizer = TfidfVectorizer(analyzer="word", token_pattern=r"(?u)\b\w+\b")
        self.word_matrix = self.word_vectorizer.fit_transform(self.titles_for_matching)

    def best_match(self, text: str) -> dict | None:
        """
        Returns the single best-matching KB record as
        {"title": ..., "url": ..., "score": ...}, or None if nothing
        clears MIN_MATCH_SCORE *and* shares enough significant words with
        the title (see the required-overlap calculation below -- normally
        2, but scaled down for titles that don't have 2 real words to
        offer in the first place). Returns the full record (not just the
        title) so callers doing step 4's KB lookup (see find_kb_match) have
        a real URL to work with, not just a label.

        The 2-word requirement (fix-013) closes a real gap: find_service_entity
        has required 2+ shared words since fix-004 (a single shared word,
        often a coincidental proper noun or unrelated content word, isn't
        enough evidence of a real match), but this function -- which is what
        find_kb_match actually calls for the live kb_match field used in
        every composed answer -- never had that same protection. Testing
        (fix-009/010/011, and the ipiresies.pdf audit in fix-012) found
        repeated cases of a single shared content word producing a
        confidently wrong match: "άδεια εκσκαφής" (excavation permit) to a
        foreign-marriage-license title sharing only "άδεια"; "μεταφορά_οστών"
        (transfer of remains) to a bin-relocation title sharing only
        "μεταφορά"; a bare "ραντεβού" to a bulky-item-removal title sharing
        only that one word. A real service reference shares more than one
        real word with its title; a coincidental one-word overlap doesn't --
        same reasoning fix-004 already used, just missing here until now.

        Known residual case this does NOT fix, documented rather than hidden:
        two real shared words can still describe a different purpose for the
        same topic (e.g. "κάδος ανακύκλωσης" reporting a BROKEN bin still
        shares 2 words -- κάδος, ανακύκλωσης -- with a title about MOVING
        bins). Word overlap, however strict, can't distinguish "report
        damage" from "request relocation" when both share the same noun --
        that distinction lives in the verb/context of the original message,
        which isn't part of what gets matched here. See notes/fix-013 for
        the full writeup of what this does and doesn't cover.

        fix-014: a flat "require 2" broke matching entirely for any KB title
        that only has 1 real content word left after generic-term stripping
        (e.g. "Κατασχέσεις", "Βεβαίωση Υψομέτρου") -- 7 of 164 titles hit
        this. Since the title itself can never contribute a 2nd word, no
        query could ever satisfy a flat "2" for these, confirmed by testing
        each with its own exact title text as the query and still getting
        no match. The requirement now scales down to whatever the title can
        actually offer (min(2, the title's own content-word count)), so a
        title with only 1 real word still needs that 1 word to genuinely
        match, but isn't held to a threshold it can mathematically never
        pass. A title with 0 real content words (none currently in the KB)
        is rejected outright rather than let the requirement hit 0 and
        accept anything -- there's no real content there to match against
        in the first place.
        """
        normalized = _strip_generic_terms(normalize(text))
        char_scores = cosine_similarity(self.char_vectorizer.transform([normalized]), self.char_matrix)[0]
        word_scores = cosine_similarity(self.word_vectorizer.transform([normalized]), self.word_matrix)[0]
        combined = CHAR_WEIGHT * char_scores + WORD_WEIGHT * word_scores

        best_idx = combined.argmax()
        best_score = combined[best_idx]
        if best_score < MIN_MATCH_SCORE:
            return None

        query_stems = {
            w[:_WORD_STEM_LENGTH] for w in normalized.split() if len(w) >= _MIN_SPAN_WORD_LENGTH
        }
        title_stems = {
            w[:_WORD_STEM_LENGTH] for w in self.titles_for_matching[best_idx].split()
            if len(w) >= _MIN_SPAN_WORD_LENGTH
        }
        if not title_stems:
            return None
        required_overlap = min(2, len(title_stems))
        if len(query_stems & title_stems) < required_overlap:
            return None

        record = self.records[best_idx]
        return {"title": record["title"], "url": record["url"], "score": float(best_score)}


# Built once here, not inside find_service_entity -- every call below
# reuses this same instance instead of reloading the KB and rebuilding
# the TF-IDF matrices every time.
_gazetteer = Gazetteer()


def find_service_entity(text: str) -> dict | None:
    """
    Turns a whole-message KB match into an entity SPAN -- i.e. the actual
    substring of `text` that overlaps with the matched title's words, not
    the KB title itself. Entities must be real substrings of the message
    everywhere else in this pipeline (see entity_extraction.py's
    _is_valid_entity); this keeps that same guarantee even though the
    matching itself works at the whole-title level, not the span level.

    Takes the longest contiguous run of the message's own words that also
    appear (accent/case-insensitive, length-filtered) in the matched
    title. Returns None if there's no confident KB match, or if the run
    is only a single word.

    That single-word cutoff matters: testing found a title matching
    purely because a common proper noun (e.g. "Ηρακλείου", which appears
    in many KB titles) cleared the score threshold on its own, producing
    a near-meaningless one-word "entity" -- exactly the "attractor title"
    failure mode v1's gazetteer notes warned about. Requiring 2+ matching
    words is a cheap, principled way to reject that class of false
    positive: a real service reference shares more than one content word
    with its KB title, a coincidental proper-noun overlap doesn't. The
    cost is losing some genuine but weak single-word matches (e.g. just
    "τέλη" for a fees question) -- acceptable, since the LLM fallback
    still gets a chance at those.
    """
    match = _gazetteer.best_match(text)
    if match is None:
        return None
    title = match["title"]

    title_words = {
        normalize(w) for w in title.split() if len(w) >= _MIN_SPAN_WORD_LENGTH
    }
    message_words = re.findall(r"\S+", text)

    best_run: list[str] = []
    current_run: list[str] = []
    for word in message_words:
        # Strip punctuation for both the match check AND what gets stored --
        # otherwise a trailing ";" or "," from the message ends up baked
        # into the returned entity text.
        stripped = word.strip(".,;!;·")
        if len(stripped) >= _MIN_SPAN_WORD_LENGTH and normalize(stripped) in title_words:
            current_run.append(stripped)
            if len(current_run) > len(best_run):
                best_run = current_run
        else:
            current_run = []

    if len(best_run) < 2:
        return None
    return {"text": " ".join(best_run), "type": "service"}


def find_kb_match(query: str) -> dict | None:
    """
    Step 4 of the pipeline: looks up the real KB record for `query`,
    returning {"title": ..., "url": ..., "score": ...} or None if nothing
    clears the confidence threshold.

    Different from find_service_entity above, and used for a different
    purpose: that function extracts a validated SPAN of the original
    message for the `entities` list (step 1). This one returns the actual
    KB record itself -- title AND url -- since a later answer-composition
    step needs a real link to ground an answer in, not just a labeled
    span. Per the original pipeline design, this is meant to be called
    with the already-resolved `service` field from structured_intent.py
    (a cleaner, LLM-narrowed query), not the raw noisy message -- so it's
    a second, independent lookup, not a reuse of whatever
    find_service_entity happened to match during entity extraction.
    """
    return _gazetteer.best_match(query)
