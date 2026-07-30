# puremonotheism-research

Generates Quran-alone research articles from the corpus at
`Motropolis/puremonotheism-data`. Same CLI runs locally and in CI.

## Two ways to run it

**Locally**, for iterating on a question:

```bash
export ANTHROPIC_API_KEY=sk-...
python -m research.cli plan  "how does the Quran describe salat?"
python -m research.cli write "how does the Quran describe salat?" --roots s6-l-w
```

**On GitHub Actions**, weekly or on demand: Actions tab -> research ->
Run workflow. Drafts arrive as a pull request. Merging is publishing.

Add `ANTHROPIC_API_KEY` under Settings -> Secrets -> Actions first.

## What stops tafsir leaking in

The drafting model has extensive training data about the Quran, including
classical commentary. Instructing it to "read the Quran alone" does not remove
that knowledge — it only hides the influence. Three layers instead:

1. **The evidence packet is the only context.** Verses, roots, occurrence
   counts and Lane entries are retrieved from the corpus and passed in. The
   model is not asked to recall anything.
2. **A mechanical check** runs first because it is free and cannot
   hallucinate. Any verse reference outside the packet, any mention of
   hadith, named commentators, occasions of revelation, Meccan/Medinan
   classification, or scholarly consensus fails the draft immediately.
3. **An adversarial verifier** is a separate call instructed to find fault.
   Self-review in the same context rubber-stamps; this does not.

None of this is airtight. It makes contamination *detectable*, which is the
achievable goal. Human review remains the last step, and the PR template
carries the checklist.

## What "learning" actually means here

Models do not learn from their own output. There is no weight update. What
compounds is `findings/observations.json`: after an article is merged,
`publish` extracts structured observations and open questions, and future
packets on the same roots include them. Article fifty inherits fifty
articles of retrieved groundwork. That is retrieval, not understanding, and
the prompts tell the model to treat prior observations as leads to verify
rather than as established fact.

Nothing is labelled a "discovery". These are observations about textual
usage, and the wording matters because readers will test them.

## Cost

Roughly 40-60k input tokens per article across drafting and verification,
plus retries. Budget accordingly before turning the schedule up.

## Gotchas

- Scheduled workflows on public repos are disabled after 60 days of repo
  inactivity. GitHub emails first.
- Cron on Actions is best-effort and often runs late.
- The corpus cache key is pinned to a corpus version. Bump it in the workflow
  when you publish a new data tag, or runs will use stale files.
