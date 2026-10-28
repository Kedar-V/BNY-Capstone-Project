# IMeeting - Oct 2

## Meeting Notes: October 2, 2026

### 1. Narrow Technical Focus

For the next phase, we will focus on building and testing extraction pipelines for **two corporate actions**:

* **Tender Offers** — Kedar
* **Mergers** — Aaron and Aesha

The goal is to get working extraction approaches for these two actions first before expanding to the remaining corporate actions.

### 2. Test Existing SEC / EDGAR Tools

Aesha and Aaron will test the open-source **edgartools** package:
[https://github.com/dgunning/edgartools](https://github.com/dgunning/edgartools)

We want to understand:

* How much filing information it can retrieve and structure for us
* Whether it can identify sections/items in a useful way
* How well it works across the filing types we care about
* Whether any parts of the repo can be reused or extended

Initial observation: `edgartools` seems strongest for common filings such as **8-Ks** and may not support Schedule TO and other corporate-action filings as well. If useful, we can clone/build on parts of the repository rather than starting everything from scratch.

After reviewing the tool, we will decide:

1. What parts of extraction can already be handled with existing tools
2. What additional extraction logic we need to build ourselves
3. Whether GLiNER needs tuning or additional models/methods are needed

***

## 3. Evaluation / Reference Dataset

Since we have not found a reliable public ground-truth dataset for all of our target corporate actions, we will create a **standardized reference dataset** ourselves.

### Proposed Approach

* Load historical filings using the SEC API
* Send the full or relevant filing content to multiple LLMs
* Use **three LLMs** to independently extract the same structured fields
* Compare the outputs to identify agreement, disagreement, and uncertain cases
* Use this as a consistent reference set for evaluating our smaller/faster extraction pipeline

This is not true external ground truth, but it gives us a standardized benchmark when no labeled dataset is available.

### Standardization

Pranshul will set up the workflow in **StackAI** and create a common prompting structure so that:

* Everyone asks for the same schema
* The extraction instructions are consistent
* The same LLMs are used across corporate actions
* Outputs can be compared and combined easily

Aesha, Pranshul, and Alex will split the LLM extraction work across different corporate actions.

### Target Scale

* Aim for roughly **1,000–2,000 filings**
* Produce one standardized extracted dataset covering multiple corporate actions
* Use this dataset to evaluate whether our proposed extraction pipeline can approach the quality of the larger LLM-based extraction process

### Main Question

The main evaluation question becomes:

> Can we build a cheaper, faster, and more auditable extraction pipeline that produces results comparable to the multi-LLM reference extraction?

Disagreements between the LLMs or particularly important examples can later be manually reviewed rather than manually labeling the entire dataset.
