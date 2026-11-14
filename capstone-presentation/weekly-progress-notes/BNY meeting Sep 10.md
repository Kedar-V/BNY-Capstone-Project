# BNY meeting — Sep 10

# Weekly Connect with BNY Stakeholders - Sep 10th

## Attendees

### Duke MIDS Student Team

Kedar, Aaron, Alex, Pranshul, and Aesha

### BNY AI Hub Team

Adler, Tianji, Jahnavi, and Adil

## Purpose of the Meeting

* Narrow the initial scope of the corporate actions project.
* Discuss potential data sources and data access requirements.
* Understand existing industry solutions and workflows.
* Define possible product directions, evaluation metrics, and ROI methodology.
* Establish next steps for research before beginning implementation.

## Agenda

* Review the proposed corporate actions pipeline.
* Discuss the initial event types to support.
* Evaluate open, academic, and commercial data sources.
* Review SmartStream and other industry solutions.
* Discuss technical performance metrics and business-impact metrics.
* Define potential product concepts and downstream use cases.
* Discuss project budget and available resources.

## What Was Discussed and Decided

### Project Scope and Architecture

* The proposed pipeline is:
  **Unstructured corporate action notice → Structured event extraction → Event linking and temporal reasoning → Downstream portfolio or accounting action → Audit log**
* The initial project should focus on a small number of corporate action types rather than attempting to support every possible event.
* Potential Phase 1 corporate action types include:
  * Cash dividends
  * Forward and reverse stock splits
  * Spin-offs
  * Mergers
* Additional event types, such as stock dividends, rights issues, tender or exchange offers, and redemptions, can be considered in a later phase.
* The architecture should be modular and adaptable so that additional corporate action types can be added without rebuilding the entire system.
* BNY emphasized that a robust solution for two event types would be more valuable than a broad but unreliable solution.

### Industry Context and Existing Solutions

* SmartStream is an established industry solution used by major custodian banks, including BNY.
* The project is being driven by BNY’s AI Hub as an exploratory innovation project.
* The goal is not necessarily to replace SmartStream or another existing system.
* The team should study existing solutions to understand the industry baseline and identify areas where an AI-native approach could improve:
  * Cost
  * Accuracy
  * Processing speed
  * Manual effort
  * Risk management
  * Workflow efficiency
* The team should research SmartStream, Broadridge, FIS, BetaNXT, DTCC-related services, and relevant S\&P products, with particular attention to actual user workflows and exception handling.

### Data Strategy

* The team should prioritize free and academic data sources during the initial phase.
* SEC EDGAR appears to be a strong starting point for real, unstructured corporate action notices.
* CRSP through Duke’s WRDS access may provide useful structured market and price data.
* Commercial sources may be useful for benchmarking or ground truth, but cost, licensing, and access restrictions could become project blockers.
* The team should access and sample the datasets rather than only reviewing their documentation.
* Data sources should be evaluated based on:
  * Corporate action types covered
  * Historical coverage
  * Timeliness
  * Raw versus structured format
  * Security and entity identifiers
  * Available fields
  * Data quality and completeness
  * Ground-truth potential
  * Access method
  * Cost and licensing restrictions
  * Suitability for Fortune 500 and large public companies

### Metrics and ROI

* Technical performance metrics and business-impact metrics should be treated separately.
* Potential technical metrics include:
  * Precision
  * Recall
  * F1 score
  * Event classification accuracy
  * Field extraction accuracy
  * Event-linking accuracy
  * Temporal reasoning accuracy
  * False-positive and false-negative rates
  * Processing latency
  * Cost per processed event
* Potential business-impact metrics include:
  * Human hours saved
  * Reduced vendor or platform costs
  * Reduced manual processing effort
  * Fewer missed corporate actions
  * Reduced operational or regulatory risk
  * Avoided penalties or losses
  * Faster processing
  * Potential revenue opportunities captured
* BNY may not be able to provide proprietary asset volumes or processing data.
* The team should therefore develop a defensible ROI methodology using public industry information, reasonable labor-cost assumptions, published benchmarks, vendor materials, and known API or infrastructure costs.
* An exact ROI number is not required at this stage. The immediate goal is to define the variables, assumptions, and methodology that could support a future ROI estimate.

### Product Direction and User Experience

* Before significant implementation begins, the team should develop a small number of concrete product concepts.
* Each concept should define:
  * The specific problem being solved
  * The target user
  * The corporate action types covered
  * The end-to-end workflow
  * The user experience
  * The level of automation
  * The required human review
  * The expected business value
  * The feasibility within the capstone timeline
* Possible product directions include:
  * Analyst copilot
  * Event-review interface
  * Automated background processing service
  * Human-in-the-loop workflow
  * Exception-management system
* The team must determine which parts of the workflow should be automated, recommended to a user, or subject to human approval.
* Risk and the potential impact of incorrect actions should guide the automation boundary.

### Downstream Workflow

* The team should research what happens after a corporate action is detected.
* A generic downstream flow may include:
  **Event detection → Identify affected securities and accounts → Calculate required action → Update downstream systems → Notify relevant parties → Create an audit record**
* Understanding the downstream process will help the team identify which corporate actions have the greatest operational, financial, or regulatory impact.

### Budget and Resources

* BNY is exploring whether Duke can invoice BNY for a project budget.
* Potential uses include:
  * LLM and API tokens
  * Premium datasets
  * API keys
  * Infrastructure
  * Other project-related resources
* The team will also ask David about available Duke departmental funding or capstone resources.
* Meeting recordings cannot be shared externally through Teams or OneDrive because of BNY’s security and data-retention policies. Notes and presentation slides will serve as the primary documentation.

## Action Items

### Student Team

| Action Item                                      | Subtasks                                                                                                                                                                                   | Status |
| ------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------ |
| Share the current presentation with the BNY team | Send the latest slide deck and confirm receipt                                                                                                                                             | Done   |
| Perform a detailed data-source analysis          | Access and sample each dataset; compare coverage, fields, quality, timeliness, identifiers, ground-truth potential, access methods, cost, and licensing                                    | To do  |
| Conduct an industry-solution analysis            | Research SmartStream, Broadridge, FIS, BetaNXT, DTCC-related services, and S\&P products; focus on workflows, rules, AI capabilities, exceptions, auditability, and user experience        | To do  |
| Conduct a deeper literature review               | Review academic, conference, industrial, vendor, and corporate-action research covering extraction, entity resolution, event linking, temporal reasoning, retrieval, and agentic workflows | To do  |
| Develop product concepts                         | Define the problem, target user, workflow, automation boundary, human-review requirements, value, and feasibility for each proposal                                                        | To do  |
| Define technical performance metrics             | Select appropriate metrics for extraction, classification, event linking, temporal reasoning, latency, and cost                                                                            | To do  |
| Develop an ROI methodology                       | Identify value and cost variables, document assumptions, collect public benchmarks, and create an estimation framework                                                                     | To do  |
| Research downstream custody workflows            | Identify downstream actions, affected securities/accounts, operational risks, and high-impact corporate action types                                                                       | To do  |
| Ask David about Duke resources                   | Confirm whether funding or departmental resources are available for APIs, datasets, tokens, or infrastructure                                                                              | To do  |

### BNY Team

| Action Item                                                                          | Subtasks                                                                                                   | Status      |
| ------------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------- | ----------- |
| Discuss the team’s questions with Lauren and the corporate-action event-capture team | Request guidance on priority event types, common use cases, downstream workflows, and available benchmarks | To do       |
| Provide feedback after the discussion with Lauren                                    | Share any relevant updates, recommendations, or clarifications with the student team                       | To do       |
| Continue investigating the BNY/Duke project budget                                   | Clarify potential funding for data, API access, LLM tokens, and other project expenses                     | In progress |

## Questions for the Next Research Cycle

* Which open datasets are most suitable for the first prototype?
* What ground truth can realistically be created?
* Which two to four corporate action types should be prioritized?
* What does the workflow of a corporate actions professional look like?
* What should the proposed product look like from the user’s perspective?
* Which steps should be automated and which should require human approval?
* What existing research and benchmarks can be used for comparison?
* Which technical metrics should be used to evaluate the system?
* Which business-impact metrics should be used to demonstrate value?
* What assumptions and variables should be included in the ROI methodology?
* Which product direction offers the best balance of feasibility, efficiency, cost savings, and risk reduction?
