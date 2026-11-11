# Week Oct 28

# BNY Capstone – Weekly Meeting Notes (Oct 28, 2026)

Oct 28, 2026 · @Aesha Gandhi

## Summary

This week the team tightens the extraction pipeline (tender offers, mergers, GLiNER retraining) while Aesha, Alex and Pranshul each research one downstream agent use case for BNY. The agents are built on ground-truth data first, so extraction accuracy is not a blocker. The week ends with a BNY update deck covering both tracks.

## Extraction pipeline

Kedar and Aaron are standardizing their extraction processes, each on a different filing type.

| Owner | Focus         |
| ----- | ------------- |
| Kedar | Tender offers |
| Aaron | Mergers       |

Shared work this week:

* Retrain GLiNER using more validation samples
* Update pipelines to extract fields such as CUSIP and ISIN manually

## Downstream agent research

The team brainstormed many agent ideas and will dig into three: how each fits the pipeline, whether it is useful, and how it benefits BNY. Implementation sketches start after tomorrow's meeting, once BNY feedback shows which ideas are useful.

For now, agents are built as if using ground-truth data. That gives a baseline setup and lets the team think through implementation without waiting on extraction or accuracy improvements.

| Agent                 | Owner    | What it does                                                                                                                                                    |
| --------------------- | -------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Vendor reconciliation | Pranshul | Compares filing-derived terms with vendor and internal event records, investigates mismatches, and files a discrepancy ticket with findings                     |
| Amendment impact      | Aesha    | Diffs versions on an amendment, finds affected clients through custody positions, drafts tailored notices for ops approval, and updates deadlines and calendars |
| Client briefing       | Alex     | Reads a client's holdings and watchlist and produces a daily or weekly brief of relevant events with evidence links                                             |

## Full list of use case ideas

* **BNY internal (Asset Servicing / Corporate Actions):** event creation and scrubbing, vendor reconciliation, amendment tracking, deadline calendar, prioritized review queue, audit trail, exposure view, workload and risk forecasting, mini-tender and unusual-offer flags
* **BNY clients:** timely notification, amendment alerts, election workflow prep and fiduciary documentation (asset managers and funds); portfolio-level digest and securities lending flags (asset owners and pensions); structured event feed (hedge funds, if BNY offers it as a data product); advisor briefings (wealth and advisory)
* **Operations agents:** filing triage, event builder, reconciliation, amendment impact, deadline watchdog, exception handling, data-quality monitor
* **Client-facing agents:** client briefing, Q\&A assistant, election prep, securities lending, relationship-manager copilot
* **Multi-agent and cross-system:** corporate-actions pipeline with a reviewer agent, cross-action correlation, scenario agent, regulatory and audit agent, onboarding agent

## Design principles for the pitch

* **Humans approve outbound actions.** Agents draft and prepare; a person sends notices, submits elections, or changes records. Autonomy can grow as evaluation scores justify it.
* **Evidence-first.** Every agent output cites source passages, which makes automation auditable.
* **Confidence-gated autonomy.** Field-level evaluation sets the thresholds for auto-approve versus review.
* **No investment advice.** Agents surface information and deadlines, not tender or don't-tender guidance.
* **Full logging.** Every agent step and tool call is recorded for audit.

## BNY update slide plan

This week's update has five slides. Keep it high level and not overly technical.

| # | Slide                          | Presenter    | Content                                                                         |
| - | ------------------------------ | ------------ | ------------------------------------------------------------------------------- |
| 1 | Extraction pipeline and tuning | Kedar, Aaron | Progress on extraction and tuning for tender offers (Kedar) and mergers (Aaron) |
| 2 | Agentic use cases overview     | TBD          | One slide introducing the ideas at a high level                                 |
| 3 | Vendor reconciliation agent    | Pranshul     | How the use case fits the workflow and helps BNY                                |
| 4 | Amendment impact agent         | Aesha        | How the use case fits the workflow and helps BNY                                |
| 5 | Client briefing agent          | Alex         | How the use case fits the workflow and helps BNY                                |

## Action items

* Kedar: standardize the tender offer extraction process
* Aaron: standardize the merger extraction process
* Kedar, Aaron: retrain GLiNER with more validation samples
* Kedar, Aaron: update pipelines to extract CUSIP, ISIN and similar fields manually
* Pranshul: research the vendor reconciliation agent and prepare a slide
* Aesha: research the amendment impact agent and prepare a slide
* Alex: research the client briefing agent and prepare a slide
* Team: after tomorrow's meeting, use BNY feedback to start sketching agent implementations on ground-truth data

**Open question:** who presents the agentic use cases overview slide?

**Parked:** VersionRAG. Revisit once full data extraction is visible, not now.
