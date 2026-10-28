# Capstone Presentation - Oct 23

## BNY Capstone Class Presentation Meeting Notes — October 23, 2026

[https://docs.google.com/presentation/d/10uryww9HnSAC4b\_\_vqDpEVBzTLh\_\_RVZ3wsavtdXeRE/edit?usp\=sharing](https://docs.google.com/presentation/d/10uryww9HnSAC4b__vqDpEVBzTLh__RVZ3wsavtdXeRE/edit?usp=sharing)

### Meeting Purpose

* Presented the **mid-semester progress** of the BNY Corporate Action Intelligence capstone.
* Walked through:
  * the corporate-action problem,
  * the extraction architecture,
  * how multiple extraction methods are combined,
  * reference-data creation and evaluation,
  * the interactive demo,
  * current limitations,
  * and next steps. Class Capstone Presentation 10\_… Class Capstone Presentation 10\_…
* The presentation emphasized the goal of turning long SEC filings into **structured, source-grounded corporate-action records** that can support BNY alerts and downstream workflows. Class Capstone Presentation 10\_…

### Project / Technical Update Presented

* Explained the pipeline from:
  * SEC search and filing retrieval,
  * document cleaning,
  * candidate extraction,
  * concise structured records,
  * verification/reasoning,
  * canonical event state,
  * and client alerts. Class Capstone Presentation 10\_…
* Reiterated that the extraction system combines several approaches because they have different strengths and failure modes:
  * keyword / regex rules for exact formats,
  * GLiNER for fast entity extraction,
  * LLMs for contextual reasoning and reference-data generation,
  * human review for selected verification. Class Capstone Presentation 10\_…
* Shared that the team has generated **571 LLM-labeled reference records so far**, with supporting source quotes retained for extracted fields. Class Capstone Presentation 10\_…
* Explained the evaluation goal as achieving **LLM-level accuracy at lower cost and latency**, using the LLM reference set plus human spot checks for pre-deployment evaluation and backward LLM checks for continuous validation. Class Capstone Presentation 10\_…
* Presented current limitations, including:
  * no fully independent ground truth,
  * only part of the five-action scope currently built,
  * the difference between individual filings and full events,
  * and limited visibility into BNY’s internal process. Class Capstone Presentation 10\_…

***

## Questions / Discussion

### 1. Using Multiple Models to Cross-Verify Ground Truth

* We were asked whether using **multiple LLMs to cross-check the reference data** would improve the ground-truth process.
* The team explained that the current model being used, **GPT-6.1 Sol**, is already performing strongly on the extraction task.
* Multiple-model agreement could provide another validation signal, but it does not automatically make the output true because multiple models could still make the same mistake.
* Our current priority is to:
  * use a strong LLM reference,
  * retain supporting passages,
  * and manually verify a sample.
* This also connects to the limitation we already presented: the LLM-generated reference set is not fully independent ground truth. Class Capstone Presentation 10\_… Class Capstone Presentation 10\_…

### 2. Why Build a Pipeline if LLMs Already Perform Well?

* A question prompted us to clarify the main technical motivation of the project.
* In an ideal scenario, if cost, latency, and scale were irrelevant, we could simply send every filing to a powerful LLM and ask it to extract the required fields.
* However, this is not practical at production scale because:
  * filings can be extremely large,
  * LLM processing is relatively expensive,
  * latency becomes important across many events,
  * and full-document LLM calls can still fail or time out.
* Our goal is therefore to use strong LLM outputs on a **sample/reference set**, then build a cheaper, faster pipeline that can approach the same level of accuracy using structured methods such as rules, GLiNER, and targeted reasoning.
* The overall objective is **LLM-level performance at a fraction of the cost**, rather than replacing LLMs simply for the sake of replacing them. Class Capstone Presentation 10\_… Class Capstone Presentation 10\_…

### 3. How Are the Extraction Methods Combined?

* We were asked to clarify how the different extraction techniques fit together.
* We re-explained that they are **complementary rather than competing approaches**.
* General flow:
  * deterministic rules / pattern matching handle highly structured information,
  * GLiNER proposes entities and exact text spans,
  * LLMs handle more contextual or complex interpretation,
  * human review is used for selected validation and difficult cases.
* Each method compensates for weaknesses in the others.
* The point is not to choose one "best" model, but to build a staged pipeline where the simplest reliable method handles each task. Class Capstone Presentation 10\_…

### 4. Why Not Ask BNY for More Data or Internal Process Information?

* We were asked why the team cannot simply request more BNY data or detailed information about their internal processing pipeline.
* We explained that there are **proprietary, confidentiality, and access limitations** around internal BNY data and workflows.
* This is why the current project is intentionally based largely on **public SEC EDGAR filings**.
* We also acknowledged that our limited view of BNY’s process is one of the project’s current limitations, which is why SME feedback sessions are especially useful for validating whether the proposed workflow and outputs are realistic. Class Capstone Presentation 10\_…

***

## Annie’s Feedback

### 1. Incorporate Explainable AI

* Annie suggested considering whether techniques or concepts from the course on **explainable AI** could strengthen the project.
* This aligns well with the current architecture because the project already emphasizes:
  * exact supporting quotes,
  * source traceability,
  * confidence scores,
  * structured intermediate records,
  * human review.
* Potential next step:
  * identify specific explainability techniques from class that could provide more interpretable reasoning or confidence around extracted fields, rather than relying only on raw model confidence.

### 2. Include Costs and Error Rates

* Annie suggested making the evaluation more concrete by explicitly discussing:
  * processing cost,
  * error rates,
  * and potentially the trade-off between accuracy and cost.
* This fits directly with the project’s stated objective of achieving strong LLM-like accuracy at lower cost and latency.
* The presentation already includes an ROI framework with:
  * released labor hours,
  * avoided errors,
  * build/integration cost,
  * run/maintenance cost,
  * AI processing cost,
  * governance/platform cost. Class Capstone Presentation 10\_…
* The next step is to connect that framework to **measured technical results**, for example:
  * cost per filing,
  * runtime per filing,
  * field-level error rate,
  * LLM baseline cost,
  * pipeline cost,
  * accuracy difference between the two.

***

## Key Takeaways

* The presentation helped clarify that the project’s goal is **not simply to outperform an LLM**, but to approximate strong LLM extraction quality in a way that is more scalable, auditable, and cost-efficient.
* Questions highlighted the need to communicate more clearly:
  * why the hybrid pipeline is necessary,
  * how its extraction methods work together,
  * and why the LLM reference dataset is a benchmark rather than perfect ground truth.
* The discussion also reinforced two useful additions to the evaluation:
  * **explainability**, and
  * **quantitative cost/error comparisons**.

***

## Next Steps

* Continue expanding and manually validating the reference dataset.
* Measure pipeline performance **field by field** against the reference set.
* Quantify:
  * accuracy,
  * completeness,
  * error rates,
  * runtime,
  * cost per filing/event.
* Compare those values directly against the strong LLM baseline.
* Explore explainable-AI techniques that can strengthen field-level interpretability and human review.
* Continue event-level tracking across amendments rather than treating filings independently.
* Continue development of downstream tasks such as:
  * client notification drafts,
  * amendment/change alerts,
  * exception queues. Class Capstone Presentation 10\_…
* Refine how we explain the role of BNY SME feedback given the limits on access to proprietary internal data and processes.
