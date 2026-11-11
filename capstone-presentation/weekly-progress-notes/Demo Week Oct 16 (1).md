# Demo Week Oct 16

# BNY Capstone — Current Team Status / Meeting Notes

**Date:** October 15, 2026
**Project:** Corporate Action Intelligence
**Current Focus:** Tender offers and mergers, extraction pipeline development, evaluation framework, and interactive demo design

## 1. Where We Are Now

The project has moved from broad research and architecture design into **implementation and evaluation**. We now have a clearer end-to-end workflow for turning SEC filings into structured corporate-action records, and the current work is focused on making the extraction reliable, measurable, and useful for downstream business workflows.

At this stage, the main technical focus is on **tender offers and mergers** rather than trying to implement all corporate-action types at once. The broader architecture is still intended to support exchange offers, rights issues, and conversions later. 10\_16 BNY Client Demo

## 2. Current End-to-End Workflow

The team’s working pipeline is:

1. **Identify relevant SEC filings**
   * Use SEC EDGAR metadata to discover and index filings.
2. **Retrieve the filing package**
   * Pull the main filing and relevant exhibits / related documents.
3. **Normalize documents**
   * Convert raw HTML into clean, searchable text.
4. **Extract candidate facts**
   * Identify fields such as parties, offer price, dates, ratios, conditions, and status.
5. **Preserve evidence and context**
   * Keep supporting source passages with extracted values.
6. **Reason across filings / amendments**
   * Resolve conflicting values and determine which terms are current.
7. **Create a canonical event record**
   * Maintain one structured current state for the corporate action.
8. **Support downstream workflows**
   * Use the structured record for alerts, version history, client notifications, and other operational tasks. 10\_16 BNY Client Demo

## 3. Technical Extraction Work

### Tender Offers

* Tender offers are being treated as **event-level document packages**, not isolated filings.
* The relevant filing set can include:
  * Schedule TO
  * Offer to Purchase
  * SC 14D-9
  * amendments such as SC TO-T/A or SC 14D-9/A
* The main idea is that different documents are authoritative for different fields.
* The pipeline is being designed so later amendments update prior terms rather than create unrelated records.

### Mergers

* Merger extraction is being developed in parallel.
* Work includes:
  * identifying relevant filing types,
  * extracting structured fields,
  * standardizing outputs,
  * and retaining source passages for each extracted value.
* The merger reference-data prompt has been tightened so categorical fields and dates are normalized consistently across filings.

## 4. Extraction Methodology

The team is currently using a **structure-first approach** rather than applying extraction over entire filings indiscriminately.

The working idea is:

**Classify document → route to relevant section → bound local context → extract field → reconcile across sources**

The appendix pipeline currently describes:

* document-role classification,
* structure routing,
* bounded local windows,
* GLiNER / regex extraction,
* and source-aware reconciliation. 10\_16 BNY Client Demo

The goal is to use simpler deterministic methods where possible and reserve more contextual NLP / LLM reasoning for harder fields.

## 5. Evaluation / Ground Truth Work

A major recent focus has been creating a reliable evaluation benchmark.

Because there is no complete public labeled dataset for the corporate actions we care about, the team is building a **standardized reference dataset** from historical SEC filings.

Current process:

* collect historical filings,
* use one standardized schema and prompt,
* run filings through an LLM to generate structured reference outputs,
* normalize field formats,
* retain supporting source passages,
* manually review ambiguous or high-impact examples. 10\_16 BNY Client Demo

This is intended to provide a consistent benchmark for evaluating:

* field-level accuracy,
* completeness,
* source grounding,
* and amendment handling.

### Important clarification

This dataset is being treated as a **reference benchmark**, not perfect external ground truth.

## 6. Standardization Work

The team has also been improving how LLM-generated reference data is formatted.

Recent changes include:

* controlled categories for fields such as `consideration_type`,
* standardized date formats,
* standardized cash and stock consideration formats,
* normalized event status values,
* more consistent entity naming,
* and keeping detailed source wording in `passages` rather than in the normalized field itself.

The goal is to ensure that the reference dataset can be compared programmatically against our own extraction pipeline without differences caused only by wording or formatting.

## 7. Backward Validation

The team is also exploring **LLM backward validation**.

The idea is:

* take an extracted field,
* send the value and the filing back to an LLM,
* ask whether the extracted value is explicitly supported by the source text.

This is intended to approximate how a human reviewer would check a structured value against the original filing and gives an additional measure of grounding quality. 10\_16 BNY Client Demo

## 8. Interactive Demo Development

In parallel with the technical work, the team is designing an interactive React demo to communicate the business use case.

The current demo concept has two views:

### BNY Operations View

* SEC filings monitor
* tender-offer / merger event records
* highlighted source passages
* structured extracted fields
* company-level event history
* version and amendment tracking

### Client View

* announcement notifications
* amendment notifications
* event summaries
* subscriptions / watchlists
* suggested next steps
* deadline or change alerts

The demo is meant to show **what the extraction layer enables**, not to imply that all downstream functionality is already implemented.

## 9. Current Demo Story

The preferred demo flow is:

1. Show new filings arriving from EDGAR.
2. Open a tender-offer filing.
3. Show relevant passages highlighted.
4. Show the structured fields extracted from those passages.
5. Open the tender-offer event record.
6. Show version history.
7. Process a later amendment.
8. Highlight what changed, such as:
   * offer price,
   * expiration date.
9. Switch to the client-facing view.
10. Show an amendment notification and suggested next steps.

This keeps the demo focused on business value rather than technical implementation details.

## 10. Current Challenges

* There is still no strong external labeled dataset covering all target corporate actions.
* Different filing types have different structures, so extraction logic cannot be completely uniform.
* Some fields are easy to normalize, while others are highly contextual and conditional.
* Amendment handling and conflict resolution remain important technical challenges.
* The team still needs to determine which downstream workflows are most important to BNY.
* Trust and review requirements for extracted values are still being clarified.

## 11. Open Questions for BNY

The team plans to use stakeholder discussions to better understand:

* Which downstream tasks are highest priority?
* Which steps in the current workflow require the most manual effort?
* What evidence would analysts need in order to trust and use extracted values?
* Which extraction errors would have the greatest operational or business impact?
* Are there gaps in the current proposed workflow or demo?
* Which client-facing outputs would be most valuable? 10\_16 BNY Client Demo

## 12. Immediate Next Steps

* Continue building tender-offer and merger extraction pipelines.
* Continue generating standardized reference data.
* Validate extraction outputs against the reference dataset.
* Test backward validation and grounding checks.
* Improve amendment / version reconciliation.
* Continue development of the interactive React demo.
* Refine downstream client-notification and event-history use cases based on BNY feedback.
* Begin reporting more concrete extraction results once enough examples have been processed and evaluated.

## Overall Status

The project is now in the **build-and-evaluate phase**. Earlier work established the scope, filing types, data sources, and architecture. The current work is centered on making the extraction process reliable, creating a standardized evaluation benchmark, and demonstrating how that structured corporate-action data could support real BNY workflows.
