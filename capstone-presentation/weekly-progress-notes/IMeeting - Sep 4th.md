# IMeeting - Sep 4th

# Internal Team Meeting - Sep 4th

## Attendees

Aesha, Pranshul, Kedar, Aron, Alex

## Purpose of the Meeting

* Explore potential data sources for the corporate actions project.
* Clarify BNY’s expectations regarding ROI analysis.
* Identify initial corporate action categories and target companies.
* Plan the team’s next steps before presenting ideas to stakeholders.

## What Was Discussed and Decided

* The team researched several possible data sources, including SEC EDGAR, Polygon.io, FINRA’s OTC Daily List, EODHD, FMP, Alpaca, and CRSP through WRDS.
* SEC EDGAR was identified as a strong potential source because it provides real, unstructured, and publicly available 8-K filings and related documents.
* Structured sources such as Polygon.io, EODHD, FMP, and Alpaca may be useful for validating extracted corporate action information.
* CRSP through WRDS was identified as a potentially valuable academic source. The team may explore access through Duke’s subscription.
* The team also reviewed MT564 and ISO 15022 message specifications to better understand realistic corporate action output formats.
* Since real MT564 messages are proprietary, the team may need to request redacted examples from BNY or generate synthetic messages based on the relevant specifications.
* The team discussed BNY’s request to analyze the ROI of each agent developed. It was concluded that a detailed ROI analysis may not be meaningful at this early stage.
* For now, the team will focus on identifying appropriate KPIs to evaluate the effectiveness and value of the proposed agents.
* The team will initially focus on Fortune 500 companies and identify a few corporate action categories that may be most relevant to BNY.
* During the next meeting with BNY, the team will present the corporate action categories being considered and ask whether BNY has specific preferences or priorities.
* The team will take a high-level approach at this stage. Once BNY and the stakeholders provide feedback and approve the direction, the team will begin implementation.
* Before the next stakeholder discussion, each team member will independently develop possible frameworks and identify useful data sources.
* The team will then combine, organize, and refine these ideas into a unified presentation for stakeholder feedback.

## Potential Data Sources

### Raw Unstructured Notices

* [SEC EDGAR](https://www.sec.gov/cgi-srv/srqsb?text=form-type%3D8-K)
* [SEC Full-Text Search](https://efts.sec.gov/LATEST/search-index?q=%22stock%20split%22)
* [sec-edgar-downloader](https://pypi.org/project/sec-edgar-downloader/)
* [sec-api.io](https://sec-api.io/datasets/form-8k-files)
* [FINRA OTC Daily List](https://otce.finra.org/otce/dailyList)

### Structured Data Sources

* [Polygon.io](https://polygon.io/docs/rest/stocks/corporate-actions/dividends)
* [EODHD](https://eodhd.com/financial-apis/api-splits-dividends)
* [FMP](https://site.financialmodelingprep.com/how-to/how-to-track-stock-splits-and-corporate-actions-with-a-free-api)
* [Alpaca Corporate Actions API](https://alpaca.markets/blog/introducing-corporate-actions-api-announcements/)

### Academic Data Source

* [CRSP through WRDS](https://wrds-www.wharton.upenn.edu/pages/grid-items/crsp-stock-database-structure/)

### Message Standards

* [MT564 Specification](https://www.iso20022.org/15022/uhb/finmt564.htm)
* [ISO 15022 Message Layouts and Examples](https://www.euronext.com/sites/default/files/2024-02/Layouts%20ISO%2015022%20Messages-Specifications.pdf)

## Action Items

| Action Item                                                                        | Owner            | Status           |
| ---------------------------------------------------------------------------------- | ---------------- | ---------------- |
| Identify potential KPIs for evaluating the agents                                  | Team             | To do            |
| Decide which corporate action categories should be prioritized                     | Team             | To do            |
| Research Fortune 500 companies and relevant corporate action examples              | Team             | To do            |
| Ask BNY which corporate action categories and use cases are most important to them | Team             | To do            |
| Individually develop possible project frameworks and identify useful data sources  | Each team member | To do            |
| Combine and organize the team’s individual research into a unified framework       | Team             | To do            |
| Explore access to CRSP through Duke’s WRDS subscription                            | Team             | To do            |
| Ask BNY whether redacted MT564 examples can be shared                              | Team             | To do            |
| Prepare a high-level presentation for BNY stakeholders                             | Team             | To do            |
| Begin implementation after receiving stakeholder feedback and approval             | Team             | Pending feedback |
