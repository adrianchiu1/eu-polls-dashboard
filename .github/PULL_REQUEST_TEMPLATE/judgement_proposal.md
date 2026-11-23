# Judgement proposal

Use this template for any change to `config/judgements.yaml`, to a contest's tier, kind, date or
status, to a headline rule, to party grouping, or to a left-right score.
Open with `?template=judgement_proposal.md` appended to the compare URL.

**Entry:** <judgement id, or contest id>
**Raised by:** <weekly check | date-based review | challenge issue #… | owner>
**Trigger:** <what happened, in one line>

## Current

> <the entry's current decision, quoted>

## Proposed

> <the new decision>

## Evidence

- <link you opened> — <what it shows, with the date of the page>

## Options

| Option | What a reader would see | Cost |
| --- | --- | --- |
| A. <recommended> | | |
| B. Leave as is | | |
| C. | | |

**Recommendation:** <A, B or C, and why in two sentences>

## Diff summary

- `config/…`: <what changes>
- Entry fields updated: `decision`, `rationale`, `decided_on`, `review_by`, `status`

## Checklist

- [ ] `python tools/validate_config.py` passes
- [ ] Only configuration changed; no data files, no code
- [ ] The evidence links were opened, not taken from search snippets
- [ ] `decided_by` is left as it was; the owner sets it on approval

**This pull request must not be merged by its author. It waits for the owner.**
