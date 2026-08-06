# Fix 012: ipiresies.pdf coverage audit -- not a code fix, a realisation

Unlike every other entry in this file, nothing in `pipeline/` changed as a
result of this one. Logged anyway, same numbering sequence as the real
fixes, because it changed what we know is fixable versus not right now --
that's as load-bearing for what happens next as a code change is, and
deserves the same kind of record rather than living only in chat.

## What happened

User provided `ipiresies.pdf` -- a human-audited, color-coded cross-reference
of the municipality's real service catalog against the intent database
(`Expanded_Intent_Dataset_2.csv` / `dimos-intent-model`), built independently
of anything in this project. Legend: red-font services have no trained
intent; blue-font services do (green-font tag alongside names the matched
intent; yellow-highlight means only a loose/approximate match). A separate
initial list enumerates all 101 database intents, with green-font marking
intents that have no identical service on the site at all.

**Tooling note:** the PDF's text layer didn't extract via `pdftotext`
(broken/garbled, likely a font-encoding issue) and the environment has no
poppler (`pdftoppm`) for page-image rendering. Installed `pymupdf` (pure pip,
no system dependency) instead -- extracted both text and, critically, exact
font/highlight colors per span, needed to reconstruct the document's actual
color-coded meaning rather than guess at it from a garbled text dump.

## The realisation

Two lists in the PDF look similar but mean different things, and only one of
them is about missing KB coverage:

1. **RED services (94 items, later in the document)** = services with no
   *trained intent* in the old classifier. Cross-checked all 94 directly
   against our real KB via `gazetteer.find_kb_match` -- **94 of 94** matched,
   almost all at score 1.00 (word-for-word identical titles). These are
   already real, working KB entries -- the "no intent" marking is about a
   *different system's* training coverage (the old BERT classifier, which
   the current pipeline doesn't use at all), not about whether we can match
   them. Nothing to fix here; there was never a gap on our side.
2. **GREEN intents (39 items, in the initial database list)** = intents with
   *no identical service on the site at all*. This is the list that actually
   matters for coverage. Cross-checked all 39 the same way:
   - **21 returned zero match at any confidence level** -- confirmed real
     gaps, independent of the PDF's own judgment. Now a checklist in
     `backlog.md`.
   - **15 returned some match, but mostly wrong ones** -- coincidental
     shared-word matches (`μεταφορά_οστών` / transfer of remains matched a
     garbage-bin-relocation service via "μεταφορά"), new evidence for the
     already-open `open-weakpoints.md` #9 problem, not real coverage.

## What we can correct right now, and what we can't

- **Can't correct, not our problem to solve:** the 21 confirmed gaps. No
  matching-algorithm improvement -- generic-term stripping, embeddings,
  domain filtering, anything already in `backlog.md` -- can produce a
  correct match for a service that doesn't exist yet. That fix is upstream:
  the service gets built and published, then re-crawled into
  `data/heraklion_eservices.json`. Reframed the `backlog.md`
  gazetteer-enrichment entry accordingly -- it had used gas connection as an
  example of something enrichment "might fix," which was wrong on this new
  evidence.
- **Already correcting, just not resolved yet:** the 15 wrong matches are
  the same failure mode `fix-009`/`fix-010` already found and partially
  fixed -- this audit added the largest batch of concrete examples so far,
  not a new problem.
- **Genuinely new, actionable output:** the 21-item checklist itself, for
  the team to check off as each service gets implemented.

## Where this landed

- `backlog.md` -- reframed the gazetteer-enrichment entry, added the
  21-service checklist.
- `open-weakpoints.md` #9 -- added the 15 wrong-match examples as further
  evidence.
- `tried-and-failed.md` -- logged the hypothesis this audit was actually
  testing ("maybe some PDF-flagged gaps already work via our gazetteer
  anyway, since we don't depend on the old classifier") and that it mostly
  didn't hold.
