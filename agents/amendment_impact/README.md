# Amendment Impact Agent

When a later filing changes a corporate action, the agent works out what changed, whether it matters to holders,
which clients it reaches, and drafts a notice for operations to approve. It covers tender offers, mergers and rights
offerings, using the same extraction runs as the client briefing agent.

## How an amendment is handled

| Step | What happens | Code |
|---|---|---|
| 1. Event store | Filings grouped into events. Shared with the other agents. | `events/store.py` |
| 2. Diff | Replay the event's filings in order. A blank in an amendment never erases an earlier value. | `events/versioning.py` |
| 3. Triage | Rules give each change a tier. Only reworded descriptive text goes to the LLM. | `triage.py`, `llm.py` |
| 4. Checks | Reasons to hold the amendment for an operations reviewer. | `checks.py` |
| 5. Holders | Simulated clients holding or watching the affected security. | `holders.py` |
| 6. Notice | A template filled from the record, with the supporting quotes, waiting for approval. | `notice.py` |

`agent.py` runs the steps and records a trace for each amendment.

### Tiers

| Tier | When |
|---|---|
| Action needed | A deadline, price, ratio or consideration changed, or the offer was terminated or withdrawn. An estimated rights price becoming a fixed one counts. |
| Needs review | Descriptive text (conditions, holder options) says something new and nobody has judged it yet. |
| Informational | The event completed, or a settlement, closing or issuance date was set. A deadline or price stated for the first time. |
| Log only | Nothing changed: results only, restated terms, the same value written another way, or a change already reported by an earlier filing. |

A filing takes its most urgent change's tier.

### What is and is not left to the model

Dates, prices, ratios and status are compared as parsed values, so "$25.00" and "$25.00 per Share, net to the seller
in cash" are the same price. Descriptive text is compared by word overlap. Below 80% overlap it counts as changed,
and the LLM decides whether holders are affected. The LLM sees only that field's old and new wording, never the whole
filing, and must quote the new wording. A made-up quote, an error or an unsure answer leaves the change for a person.
Without `--env-file`, only answers already in `llm_cache.json` are used, and any other changed text goes to review.

### Held for review

| Code | Meaning |
|---|---|
| `price_change_window` | A tender offer's price changed with fewer than 10 business days left (SEC Rule 14e-1(b)). |
| `deadline_moved_earlier` | A deadline moved earlier, which is unusual. |
| `deadline_in_past` | The new deadline is before the amendment was filed: a typo, or a filing about an earlier offer. |
| `no_evidence` / `quote_not_found` | A change has no supporting quote, or the quote is not in the filing text. |
| `text_not_assessed` | Changed text that the LLM did not decide. |

## Data

The same inputs as the client briefing agent (see its README): the extraction runs for rights offerings, mergers and
tender offers, treated as ground truth for now, and the simulated client positions in `client_briefing/clients.json`.

## Evaluation: synthetic amendments

There is no labelled set of real amendments yet. As with vendor reconciliation, `synthetic.py` plants changes with a
known answer: it takes a real event's first filing, adds one made-up amendment two days later, and records the tier
and review codes the agent should give. Real filings after the first are left out.

13 case types, up to 15 per action: extensions, deadlines moved earlier, changes with no quote, price and ratio
changes, a tender price change too close to expiry, terminations, completions, dates set, and four that must **not**
notify (restated terms, the same values written another way, reworded text, and no change at all). Changed text is
expected to go to review with rules only, or to be action needed with the LLM.

Rules only, seed 7: 525 cases, 525 at the expected tier, review codes 100% precision and recall
(`synthetic/evaluation_summary.json`). This shows the rules do what they are meant to on clean, well-formed inputs.
It does not measure accuracy on real amendments: we wrote both the cases and the rules, and real extraction is
messier (see below).

## On the real extraction runs

The agent assesses every filing after an event's first one: 358 across the three actions.

| Tier | Rules only | Rules + LLM |
|---|---|---|
| Action needed | 96 | 135 |
| Needs review | 200 | 2 |
| Informational | 15 | 59 |
| Log only | 47 | 162 |

With rules only, almost every review is changed descriptive text: each filing's extraction words the same terms
differently (median word overlap 0.31), so rules cannot tell a reworded field from a changed one. The LLM judged 538
of the 542 text changes and called 74 material.

The first prompt (v1) called 270 material. It treated text that one filing simply left out as a change, because a
filing often describes only part of the terms. Prompt v2 says that omission or less detail is not a change; only a
contradicting or replacing term counts. Spot checks of v2's material calls found real changes (an expiration moved
from March 16 to March 19, 2026; shares per right changed from 0.057 to 0.095), but they have not been checked
systematically. Both prompts got all 45 planted text changes in the synthetic set right.

`deadline_in_past` (61) mostly flags funds that run a new tender offer every quarter under the same SEC file number,
where a results amendment for an earlier offer lands in a later one. Some of the LLM's material calls come from the
same mix-up: a tender deadline from the previous quarter's offer.

## Run it

From the repository root:

```bash
# Real amendments from the extraction runs -> output/amendment_queue.json and .csv
python -m agents.amendment_impact.agent
python -m agents.amendment_impact.agent --env-file .env        # the LLM judges changed text
python -m agents.amendment_impact.agent --event <event id>     # one event, printed
python -m agents.amendment_impact.agent --text-dir <input_text folder> ...   # also check quotes against the filing text

# Synthetic evaluation
python -m agents.amendment_impact.synthetic --seed 7 --per-type 15
python -m agents.amendment_impact.evaluate
python -m agents.amendment_impact.evaluate --env-file .env

# Tests
python -m pytest agents/amendment_impact/tests -q
```

## Not built yet

- The approval step: operations approving, editing or rejecting a drafted notice, and updating deadlines once
  approved.
- LLM-written summary sentences in the notice. Notices are templates for now, so every value is exact.
- Matching by CUSIP. Like the briefing agent, holders are matched by ticker, which many tender events lack.
- A demo page for the review queue.
