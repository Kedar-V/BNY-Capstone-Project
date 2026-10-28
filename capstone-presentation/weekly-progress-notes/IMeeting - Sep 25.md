# IMeeting - Sep 25

# BNY Capstone — Team Meeting Notes: Sep 25

## Attendees

Aesha, Aaron, Alex, Pranshul, and Kedar

## Focus

Progress Report 1, task delegation, and the initial corporate action data extraction pipeline.

## Purpose of the Meeting

* Review Progress Report 1, due September 25.
* Assign individual research and SEC filing validation tasks.
* Discuss the initial approach for extracting corporate action information from SEC filings.
* Identify relevant SEC forms, document structures, extractable fields, and promising extraction methods.

## Agenda

1. Review Progress Report 1.
2. Delegate individual research and extraction tasks for the upcoming week.
3. Discuss the initial approach to building the corporate action data extraction pipeline.

## Discussion Summary

### Data Extraction and SEC Filing Validation

* The team’s immediate priority is to investigate how relevant corporate action information can be extracted from SEC filings.
* Each team member will review the taxonomy table in `tender_offer_eda.ipynb` for their assigned corporate action.
* The preliminary mappings between corporate actions and SEC forms were AI-generated and must be independently validated.
* The team will focus on understanding the available documents and identifying promising extraction approaches. A complete extraction pipeline is not required at this stage.

For each assigned corporate action, the investigation should cover:

* **Form validation:** Identify and verify the SEC forms in which the corporate action appears.
* **Document structure:** Examine how information is presented within filings, including headings, free-form text, tables, and exhibits.
* **Extraction methods:** Experiment with keyword searches, regular expressions, pattern matching, or other appropriate techniques.
* **Field identification:** Determine which fields can be extracted and whether they align with the team’s existing data schema.
* **Data quality and limitations:** Document noise, inconsistencies, missing fields, and variations across filings.

## Corporate Action Taxonomy and Preliminary SEC Form Mappings

The following table from `tender_offer_eda.ipynb` will be used as the starting point for form validation.

| BNY Corporate Action Type | Corpus Status | Primary SEC Forms                                  | Supporting SEC Forms                | Notes                                                                                                                                 |
| ------------------------- | ------------- | -------------------------------------------------- | ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------- |
| TENDER OFFER              | Collected     | SC TO-T, SC TO-T/A, SC TO-I, SC TO-I/A             | SC 14D9, SC 14D9/A                  | Primary corpus. Prefer mixed third-party and 14D9 events for MVP v1.                                                                  |
| EXCHANGE                  | Collected     | SC TO-T, SC TO-T/A, SC TO-I, SC TO-I/A, S-4, S-4/A | SC 14D9, SC 14D9/A, 424B3, 8-K, 425 | S-4 filings are collected through the merger-exchange track. Some exchange offers also appear in Schedule TO filings.                 |
| RIGHTS ISSUE              | Collected     | 424B2, 424B3, 424B5, S-3, S-3ASR                   | 8-K, 424B4                          | Collected through EFTS 424B2/3/5 searches and rights-offering text filters. Not all 424B filings are relevant.                        |
| MERGER                    | Collected     | DEFM14A, PREM14A, S-4, S-4/A, SC 13E3, SC 13E3/A   | 8-K, 425                            | Collected through EFTS for the 2020–2025 period.                                                                                      |
| CONVERSION                | Collected     | 8-K, 424B2, 424B3, S-3, S-3ASR                     | 10-K, 10-Q                          | Collected through 8-K searches and conversion-language filters. The corpus is still noisy and may require manual event-type labeling. |

## Task Assignments

| Corporate Action | Assigned Team Member(s) |
| ---------------- | ----------------------- |
| Tender Offer     | Kedar, Pranshul         |
| Exchange Offer   | Aesha                   |
| Rights Issue     | Alex                    |
| Merger           | Aaron                   |
| Conversion       | Pranshul                |

## Action Items and Next Steps

| Owner            | Action Item                                                                                              | Status |
| ---------------- | -------------------------------------------------------------------------------------------------------- | ------ |
| Kedar, Pranshul  | Provide a simplified script or notebook for accessing the API and loading data for each corporate action | To do  |
| All team members | Load SEC filing data for the assigned corporate actions using the shared script or notebook              | To do  |
| All team members | Validate the SEC form mappings in the existing taxonomy                                                  | To do  |
| All team members | Identify representative filings for the assigned corporate actions                                       | To do  |
| All team members | Investigate the structure of relevant filings, including headings, free-form text, tables, and exhibits  | To do  |
| All team members | Identify fields that can be extracted and compare them with the existing data schema                     | To do  |
| All team members | Experiment with keyword searches, regular expressions, pattern matching, and other extraction methods    | To do  |
| All team members | Document filing variations, extraction challenges, missing information, and potential solutions          | To do  |
| All team members | Share research findings, preliminary experiments, and extraction progress at the next team meeting       | To do  |

## Expected Outcomes for Next Week

Each team member should be prepared to explain:

* Which SEC forms are relevant to the assigned corporate action.
* Whether the preliminary SEC form mappings are accurate.
* How relevant information is structured within the filings.
* Which fields can be extracted reliably.
* Which extraction methods appear promising.
* What limitations or inconsistencies were observed.
* How the findings align with the team’s existing data schema.

These findings will inform the design of the team’s initial corporate action data extraction pipeline.
