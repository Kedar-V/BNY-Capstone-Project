# IMeeting - Sep 23

# Internal Capstone Meeting Notes - Sep 23

## Attendees

Alex, Pranshul, Kedar, Aaron, and Aesha

## Purpose of the Meeting

* Research and validate potential data sources for evaluating the corporate actions pipeline.
* Identify available ground-truth data for different corporate action types.
* Address the limited availability of historical data for tender offers, exchange offers, rights issues, and conversions.
* Develop an evaluation framework for measuring performance at each stage of the pipeline.

## What Was Discussed and Decided

### Data Sources

The team explored several free or partially accessible historical datasets. More data is currently available for mergers, acquisitions, dividends, and stock splits, while ground truth remains limited for the team’s priority corporate actions, particularly tender offers, exchange offers, rights issues, and conversions.

| Source                  | Findings and Potential Use                                                                                                                                                                                       |
| ----------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Business Quant API      | Downloaded 47,548 records covering one year and 17 action types, primarily dividends. The dataset may be useful for testing event discovery, event classification, counterparty extraction, and date extraction. |
| Kaggle: Technology M\&A | Contains 1,643 historical acquisitions. This may help validate structured merger records against information extracted from source documents.                                                                    |
| Databento               | Provides a free sample of 864 records with 104 fields, including three rights issues but no tender offers. This may be useful for schema validation and testing structured fields.                               |
| Kaggle: Techsalerator   | Contains a small sample of rights-issue fields, including subscription prices and record dates. The team still needs to verify the dataset’s actual coverage and reliability.                                    |

### Addressing the Tender-Offer Data Gap

* Free historical datasets for tender offers and other priority corporate actions are limited.
* The team discussed combining SEC EDGAR-based discovery recall with a smaller manually annotated benchmark.
* LLM-assisted evaluation may be used to compare extracted fields against the original source documents and flag potential errors.
* A sample of the LLM-assisted evaluations will be manually reviewed by the team.
* This approach could help evaluate:
  * Source grounding
  * Field-level extraction accuracy
  * Amendment handling
  * Conflicting information across filings
  * The reliability of the evaluation process itself

### Evaluation Framework

* The team agreed that the pipeline should be evaluated stage by stage rather than using one overall accuracy score.
* This will make it easier to identify where errors occur and which components require improvement.
* The first three stages can largely be evaluated using SEC metadata and automated checks, with limited manual review for document normalization.
* The later reasoning, canonical-state, and notification stages will require manually labeled examples or a team-created benchmark.
* LLM-assisted evaluation may reduce manual effort for notification review, but its results should be validated against human judgments.

## Evaluation Metrics by Pipeline Stage

| Stage                        | Proposed Metrics and Evaluation Approach                                                                                                                                                                                                                    |
| ---------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1. SEC Discovery             | Measure filing discovery recall by comparing the filings identified by the pipeline with EDGAR’s official filing indexes for the same period.                                                                                                               |
| 2. Filing Retrieval          | Measure exhibit retrieval completeness by checking whether all documents listed in each filing’s index were downloaded, particularly important exhibits such as the Offer to Purchase.                                                                      |
| 3. Document Normalization    | Manually spot-check normalized text against the original HTML. Use automated character-offset checks to verify that extracted evidence can be traced back to the source document.                                                                           |
| 4. Reason / Verify / Resolve | Measure amendment detection using precision, recall, and F1 score. Evaluate whether conflicting information across filings is resolved to the correct value using manually labeled examples.                                                                |
| 5. Canonical Event State     | Measure the completeness of required fields for each corporate action type. Evaluate the accuracy–coverage trade-off to determine which fields can be automatically accepted and which require human review.                                                |
| 6. Client Notification       | Evaluate whether notifications faithfully represent the canonical event record without inventing or omitting facts. Use an LLM-judge rubric validated against human reviews. Confirm that notifications remain neutral and do not recommend client options. |

## Main Takeaways

* The available datasets are more useful for mergers, acquisitions, dividends, and splits than for tender offers and other priority actions.
* Business Quant API may be useful for large-scale testing of event discovery and field extraction.
* Kaggle’s Technology M\&A dataset may help validate merger-related records.
* Databento may support schema validation and rights-issue testing.
* The Techsalerator dataset requires additional verification before it can be used.
* For tender offers, the team will likely need to combine EDGAR-based discovery with a manually annotated benchmark.
* Automated checks are most feasible for SEC discovery, filing retrieval, and document normalization.
* Manual annotations will be necessary for reasoning, conflict resolution, canonical event state, and notification evaluation.
* LLM-assisted evaluation can help reduce manual review effort, but it must be compared against human judgments.

## Action Items

| Action Item                                                                                                                | Owner | Status |
| -------------------------------------------------------------------------------------------------------------------------- | ----- | ------ |
| Validate the Business Quant API dataset and document the action types, fields, and coverage                                | Team  | To do  |
| Evaluate whether the Business Quant records can support event discovery, classification, counterparty, and date extraction | Team  | To do  |
| Review the Kaggle Technology M\&A dataset for merger validation                                                            | Team  | To do  |
| Investigate the Databento sample and document its rights-issue fields and schema coverage                                  | Team  | To do  |
| Verify the quality and actual coverage of the Kaggle Techsalerator rights-issue dataset                                    | Team  | To do  |
| Compare the available datasets against the team’s corporate action schema                                                  | Team  | To do  |
| Define a sampling strategy for tender-offer filings from SEC EDGAR                                                         | Team  | To do  |
| Create a manually annotated benchmark for tender offers and other priority actions                                         | Team  | To do  |
| Define the filing discovery recall evaluation process using SEC EDGAR indexes                                              | Team  | To do  |
| Create automated checks for filing retrieval completeness                                                                  | Team  | To do  |
| Implement character-offset checks for document normalization and source traceability                                       | Team  | To do  |
| Prepare labeled examples for amendment detection and conflict resolution                                                   | Team  | To do  |
| Define required fields and completeness checks for each canonical event type                                               | Team  | To do  |
| Develop an LLM-judge rubric for evaluating client notifications                                                            | Team  | To do  |
| Compare LLM-judge results with human reviews and document agreement or disagreement                                        | Team  | To do  |
| Update the evaluation framework document with the agreed datasets, metrics, and validation procedures                      | Team  | To do  |



Formal Meeting Notes

[View the formal meeting notes](https://docs.google.com/document/d/1JdNgqLmn_GnmyEzBCi2amuc2FOxasIViuI0jEZvd--E/edit?usp=sharing)
