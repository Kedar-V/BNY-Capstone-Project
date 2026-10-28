# BNY Meeting - Oct 22

## BNY Weekly Meeting Notes — October 22, 2026

### Meeting Purpose

* Brief weekly project update on progress since last week’s demo.
* Reviewed how the team is incorporating recent BNY feedback and validating the extraction pipeline. 10\_22 BNY Weekly Update

### Team Update

* Shared that current work is focused on:
  * adding and validating **key dates**,
  * classifying events as **mandatory, voluntary, or mandatory with options**,
  * improving **free-text standardization**,
  * and validating the extraction pipeline across different filings and event types. 10\_22 BNY Weekly Update
* Presented the CUSIP/share-class issue found during review:
  * some tender-offer records contained multiple valid CUSIPs in one flat field,
  * but the original representation did not reliably map each CUSIP to the correct share class.
* The updated approach is to represent securities as a list / one row per share class and verify that each CUSIP is supported by the filing. 10\_22 BNY Weekly Update

### BNY Feedback / Discussion

* BNY said the project is progressing well and reiterated that they **liked the demo from last week**.
* Adler followed up on Lauren’s feedback around **free-text standardization**:
  * specifically, whether the team can identify recurring **text patterns across filings/documents**,
  * and use those patterns to help produce more consistent standardized corporate-action descriptions.
* Adler asked what the team’s **next steps** are following the current validation work.
* There was discussion around **how the CUSIP extraction should be evaluated**:
  * not just whether a CUSIP appears in the document,
  * but whether it is correctly associated with the appropriate security/share class.
* The team explained that the plan is to re-run affected filings with the revised schema and then measure accuracy at the field level, including CUSIP-by-share-class accuracy. 10\_22 BNY Weekly Update
* BNY also asked the team to share feedback from the **upcoming presentation / discussion tomorrow**, particularly anything useful learned from that audience.

### Next Steps

* Re-run tender-offer filings affected by the CUSIP schema issue.
* Compare results before vs. after the schema change.
* Measure accuracy field by field, including CUSIP-to-share-class mapping.
* Continue extending the same validation ideas to mergers.
* Investigate recurring language/text patterns that could support standardized client-ready free text.
* Incorporate key dates and mandatory/voluntary classification into the extraction/evaluation workflow.
* Report back to BNY on any useful feedback or takeaways from tomorrow’s presentation.
* Continue using evaluation to identify issues before treating outputs as verified; current outputs are still being validated against source filings. 10\_22 BNY Weekly Update

### Overall Takeaway

* Short status meeting with positive feedback.
* BNY remains supportive of the direction and is now pushing the team toward **more rigorous field-level validation**, stronger security/CUSIP mapping, and deeper exploration of **repeatable text patterns for standardized corporate-action descriptions**.
