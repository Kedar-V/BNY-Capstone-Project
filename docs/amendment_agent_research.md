# Amendment impact agent: research and scoping

Research notes on the amendment impact agent, one of three downstream agent use cases the team is exploring for BNY (alongside vendor reconciliation and client briefing). This covers what the agent does, how it fits the pipeline, whether it is useful and feasible, and a code-level sketch. Implementation starts after BNY gives feedback on which agent ideas are most useful.

Status as of Oct 28, 2026: research only. Nothing here is built yet beyond the existing extraction pipeline and demo.

---

## 1. What the agent does

Companies sometimes change a corporate action after announcing it: they extend the deadline, raise the price, or change the conditions. They tell the market by filing an amendment with the SEC (for example a Schedule TO/A for a tender offer).

When that happens, BNY has to notice it, work out what changed, and tell the clients who hold the security. If a client acts on the old deadline, they can miss out, and BNY may have to make it right.

The agent automates the preparation, and a person makes the final call:

1. **Spot it:** a new amendment is filed.
2. **Match it:** link it to the right existing event.
3. **Compare:** what is different from the previous version? (e.g. deadline Oct 10 → Oct 25)
4. **Decide if it matters:** a new deadline matters; a "the offer finished, here are the results" filing usually doesn't need a client notice.
5. **Find who's affected:** which clients hold this security (custody positions).
6. **Draft the notice:** a short, standardized replacement notice with the key facts first and source quotes.
7. **Person approves:** operations reviews and sends it; deadlines and the calendar are updated.

---

## 2. How it fits the pipeline

```
SEC search → download → clean → extract → concise record      (steps 1–5, built)
                                              │
                                              ▼
                              ┌──────── EVENT STORE ────────┐   (steps 6–7, not built yet)
                              │ link filing → event          │
                              │ apply amendment → new version│
                              │ diff → list of changes       │
                              └──────────────┬───────────────┘
                                             │ "event X changed"
                                             ▼
                              ┌──── AMENDMENT IMPACT AGENT ──┐   (downstream)
                              │ triage → checks → holders →  │
                              │ draft notice → approval queue│
                              └──────────────┬───────────────┘
                                             ▼
                               demo UI / approval → calendar      (step 8)
```

| Agent step | Where it comes from | Status |
|---|---|---|
| Detect a new amendment | SEC search (form ends in `/A`) | Built |
| Link it to the right event | Temporal event tracking | **Not built; main dependency** |
| Extract what changed | Extraction, given the previous state | Partly built |
| Compare and decide if it matters | New agent logic | To design |
| Find affected holders | BNY custody positions | BNY data; simulate |
| Draft replacement notice | Standardized descriptions work | In progress |
| Approve, update calendar | Human sign-off | To design |

The agent is effectively the first downstream use of temporal event tracking. The event store underneath it is shared foundation: the vendor reconciliation and client briefing agents need it too.

---

## 3. What our own data shows

Source: `notebooks/evaluation/tender_offers.csv` (613 LLM-labelled tender offer records) and `outputs/events.csv` (EDA over SEC filings). These are sample findings, not population rates.

### Amendments are common

- 349 of the 613 tender offer records come from amendment filings (SC TO-I/A 270, SC TO-T/A 48, SC 14D9/A 31).
- In the EDA, 599 issuer tender offer groups (by SEC file number): 97% have at least one amendment, median 3 amendments.

### Most amendments don't change anything a holder acts on

Event status of the 349 amendment records:

| What the amendment does | Records | Share |
|---|---|---|
| Completed or final results | 220 | 63% |
| Terms changed or supplemented ("Amended") | 96 | 28% |
| Offer extended | 28 | 8% |
| Terminated | 3 | <1% |
| Commenced | 2 | <1% |

So the agent's first job is triage. Notifying on every amendment would mostly create noise. (Final results still matter for payment and proration, just not for elections.)

Real extensions do appear, for example Warner Bros. Discovery (expiration extended from Jan 21 to Feb 20, 2026) and Performance Shipping (extended to Sep 18, 2026).

### Amendments are often partial

| | Expiration date missing | Offer price missing |
|---|---|---|
| Original filings (264) | 4% | 0% |
| Amendments (349) | 19% | 9% |

Amendments often restate only the items that changed ("Item 4 is hereby amended to…"). The agent has to start from the event's previous state, not treat the amendment as a complete record.

### Linking is harder than it looks

Many issuer tender offers in our sample are recurring repurchase offers by funds (e.g. A&Q, AMG Pantheon, AB Private Credit), which file a new offer every quarter or half-year. Grouping by company made separate offers look like "changed deadlines". In the EDA, a quarter of tender file-number groups span more than 581 days, so one SEC file number can hold several separate offers. The agent must tell "update to this offer" apart from "a new offer".

---

## 4. Rules and industry practice

### SEC tender offer rules (Exchange Act Rule 14e-1)

- **14e-1(b):** if the price or the percentage of shares sought changes, the offer must stay open at least **10 business days** from when notice of the change is first given to holders. The agent can use this as a sanity check: a new deadline that breaks the rule points to an extraction error.
- **14e-1(d):** an extension must be announced by **9:00 a.m. Eastern on the next business day** after the previously scheduled expiration. The window to react is short, so speed matters.
- Amendments to a Schedule TO keep the original SEC file number (seen in SEC correspondence and filings), which helps linking but isn't a unique event ID (see section 3).

### How custodians already send updates

In the SWIFT MT564 corporate action notification, field 23G "function of the message" includes `REPL` (replacement), linked to the earlier notice via a `PREV` reference, as well as `CANC` and `WITH` for cancelled or withdrawn events. The agent's output (a replacement notice tied to the original) fits how custodians already communicate changes. The ISO 20022 equivalent is the seev.031 announcement.

### Industry context

- Voluntary events are consistently described as the highest-risk corporate actions, and manual capture of terms leads to mis-keyed dates and missed elections.
- A ValueExchange survey cites data as the root cause of 56% of corporate action errors.
- Cost estimates vary widely (from about $2M per business unit per year to $1B industry-wide). Most come from vendors with an interest in automation, so treat them as indicative.

---

## 5. Is it useful?

**Yes, with a caveat.**

For:
- BNY's corporate actions SME (Lauren) told us a wrong deadline is the costliest mistake, and amendments are where deadlines move.
- Amendments are frequent (section 3), and the reaction window is short (Rule 14e-1(d)).

Caveat:
- BNY already receives event changes from vendors and DTC. The value is not discovering the change. It is **verifying it against the filing, triaging what matters, finding affected clients, and drafting consistent notices quickly**.
- This overlaps with the vendor reconciliation agent (Pranshul): a vendor-vs-filing mismatch is often an amendment. Agree where the boundary sits.

### How it helps BNY

- **Fewer deadline errors and make-goods:** every change is checked against the filing, with the source quote.
- **Faster replacement notices:** maps onto the `REPL` notification flow custodians already use.
- **Less ops time on noise:** results-only amendments are filtered out.
- **Audit trail:** what changed, which filing, who approved, when.

---

## 6. Is it feasible?

| Part | Feasibility | Why |
|---|---|---|
| Detect and compare (tender offers) | High | 349 amendment records already extracted; SEC file numbers available |
| Linking (update vs new offer) | Medium | File number + date gap + CUSIP and price; recurring fund offers are the hard case |
| Deciding whether a change matters | Medium | Event-status labels give a starting training/eval set |
| Rule 14e-1(b) check | High | Simple business-day calculation |
| Affected clients, sending, calendar | Simulated only | Uses BNY data and systems |
| Mergers | Lower | Changes come via 8-Ks, proxy supplements, amended merger agreements; S-4/As are mostly pre-effectiveness revisions |

**Suggested prototype scope:** tender offers only, built on our labelled records, with simulated holdings. Output per amendment: list of changes with quotes, a "matters to holders?" label, the 14e-1(b) check, a draft replacement notice, and an approval queue item.

**Main dependency:** event tracking. Without reliably linking an amendment to the right event, every later step can go wrong.

### Risks

- Linking errors (recurring fund offers, reused file numbers) → false change notices.
- Partial amendments that imply a change without stating the new value.
- Multiple share classes and CUSIPs per event (see the Oct 22 CUSIP issue).
- Duplicate notices if the same change appears in several filings (Schedule TO/A, 14D-9/A, press release exhibit).
- Over-automation: every outbound notice must stay human-approved.

---

## 7. How it relates to VersionRAG

They are not independent, but they sit at different levels:

- **The agent** is the whole job: amendment in → what changed → does it matter → who's affected → draft → approval.
- **VersionRAG** is a technique for searching and answering questions across versions of a document. It doesn't decide anything, find clients or draft notices.

They overlap only in the "link and compare" steps (temporal event tracking). Two ways to do those:

| Approach | How "what changed" is found | Good for |
|---|---|---|
| Structured comparison (recommended baseline) | Extract fields per filing, store each as a version, compare fields | Exact, auditable changes to known fields (dates, price, conditions) |
| VersionRAG | Keep filings as a linked set of versions and query across them | Changes not captured by fields; open questions like "what changed in Amendment 3?" |

VersionRAG could be one ingredient inside the agent later. It is parked until full extraction is visible. In one line: **the agent is what we deliver, event tracking is the foundation it needs, and VersionRAG is one optional way to build part of that foundation.**

---

## 8. Code sketch (not implemented)

### Folder layout

```
events/                      # shared foundation
  models.py                  # Event, Version, Change
  store.py                   # save/load event histories (JSON or Postgres)
  linking.py                 # which event does this filing belong to?
  versioning.py              # merge partial amendment into prior state, diff

agents/amendment_impact/
  triage.py                  # does this change matter to holders?
  checks.py                  # Rule 14e-1(b) and other sanity checks
  holders.py                 # affected clients (simulated positions)
  notices.py                 # draft replacement notice
  approval.py                # queue + calendar update + audit log
  agent.py                   # orchestrates the steps above
  evaluate.py                # score against labelled amendment pairs

data/simulated/positions.csv # fake client holdings
```

### Data models

```python
@dataclass
class Version:
    filing_id: str            # accession number
    form: str                 # "SC TO-I/A"
    filed: date
    fields: dict              # extracted values from THIS filing (may be partial)
    passages: dict            # field -> source quote

@dataclass
class Event:
    event_id: str
    file_number: str          # SEC 005-xxxxx
    cusips: list[str]
    versions: list[Version]   # append-only history, never overwritten
    current: dict             # merged "latest known" state

@dataclass
class Change:
    field: str                # "expiration_date"
    old: str | None
    new: str | None
    quote: str                # passage in the amendment
    filing_id: str
```

### Event store (foundation)

```python
def link_filing(filing, store) -> str | None:
    """Return the event_id this filing updates, or None if it's a new event."""
    # 1. same SEC file number
    # 2. within a date window of the last version (fund offers repeat every quarter)
    # 3. same CUSIP / price / parties
    # 4. still ambiguous -> ask the LLM, or flag for review

def apply_amendment(event, extracted) -> list[Change]:
    """Merge a partial amendment into the event and return what changed."""
    # A blank in the amendment does NOT erase the old value.
    # A new value replaces it -> record a Change with its quote.
```

### Agent

```python
def handle_amendment(filing):
    event_id = link_filing(filing, store)
    if event_id is None:
        return  # new event, not an amendment -> other flow

    event = store.load(event_id)
    changes = apply_amendment(event, extract(filing))

    material = triage(changes, event)          # rules first; LLM for wording changes
    if not material:
        log("results-only / no holder impact"); return

    issues = check_rules(event, changes)        # e.g. 10 business days after a price change
    holders = affected_holders(event.cusips)    # simulated positions
    notice = draft_notice(event, changes)       # template + key facts + quotes

    approval_queue.add(event, changes, notice, holders, issues)
    # on approve -> update_calendar(event); audit_log(...)
```

LLM calls only where judgment is needed: ambiguous linking, triage of wording changes (e.g. "conditions amended"), and the plain-language summary sentence in the notice. Facts in the notice come from the extracted fields, not the LLM.

### Where it becomes agentic

The version above is a fixed pipeline. It becomes agentic when the agent chooses its next step in uncertain cases, using tools:

```python
tools = [
    get_event_history,     # previous versions of the event
    search_filing_bundle,  # look in the Offer to Purchase / exhibits for a missing value
    compare_versions,
    check_deadline_rules,
    lookup_holders,
    draft_notice,
    escalate_to_reviewer,
]
```

Example: an amendment says "the expiration date is extended" but doesn't state the new date. The agent searches the attached exhibits, finds it, checks it against the 10-business-day rule, then drafts the notice, or escalates if it still can't find it.

Start with the fixed pipeline; add the tool loop only for cases the rules can't handle. Fixed parts (templates, required fields, date formats) stay rule-based for predictability and audit.

### Evaluation

Labelled amendment pairs (prior state + amendment → expected changes + material yes/no), built from the 349 amendment records paired with earlier filings by file number.

- **Linking:** update vs new offer, accuracy
- **Change detection:** did we catch every real change, and any false ones?
- **Triage:** material vs not, accuracy
- **Deadlines:** is the new deadline exactly right?

### Build order

1. `events/`: linking and versioning on tender offers, with a linking accuracy check
2. `apply_amendment` + labelled pairs
3. Triage and checks (mostly rules)
4. Simulated holders + notice template
5. Approval queue in the demo app (builds on its existing version history tab)
6. Tool loop for uncertain cases

Steps 1–2 matter for the whole team and are the most likely to take longer than expected.

---

## 9. Questions for BNY

1. When an amendment comes in today, where does your team first hear about it (vendor, DTC, issuer), and how long until a client notice goes out?
2. Which changes always trigger a client notice: deadline, price, conditions, proration, final results?
3. Do you resend the full notice, or only the changes?
4. Is working out which clients are affected a pain point, or already automated from positions?

---

## 10. Sources

- SEC Rule 14e-1: [2011 CFR text](https://www.govinfo.gov/content/pkg/CFR-2011-title17-vol3/pdf/CFR-2011-title17-vol3-sec240-14e-1.pdf), [current text](https://www.customsmobile.com/regulations/17/240.14e-1), [example Offer to Purchase applying it (Essendant, 2018)](https://www.sec.gov/Archives/edgar/data/0000355999/000119312518280626/d627175dex99a1a.htm)
- Schedule TO amendments sharing a file number: [TB Wood's SEC correspondence](https://www.sec.gov/Archives/edgar/data/0001000227/000095011605003155/filename1.txt), [Fair Isaac SC TO-I/A](https://www.sec.gov/Archives/edgar/data/0000814547/000095013405004640/filename9.htm)
- MT564 messaging: [Field 23G: Function of the Message](https://www.iso20022.org/15022/uhb/mt564-4-field-23g.htm), [Clearstream on REPL notifications](https://www.clearstream.com/caas/v1/media/1288672/data/aaacf6be4a0b6ce69b6d61eb8b15f4c6/a11198-en.pdf), [iotafinance: REPL](https://www.iotafinance.com/en/SWIFT-ISO15022-View-Code-REPL.html)
- Industry context: [The ValueExchange: the data problem](https://thevalueexchange.foleon.com/asxcorporateactions/corporate-actions-2021/what-is-the-problem/), [Oxera: corporate action processing](https://www.oxera.com/wp-content/uploads/2018/03/Corporate-action-processing.pdf), [DTCC: the hidden rising cost of corporate actions](https://dtcc.com/dtcc-connection/articles/2024/may/01/the-hidden-rising-cost-of-corporate-actions)
- VersionRAG: [arXiv 2510.08109](https://arxiv.org/abs/2510.08109v1)
- Hindsight (agent memory): [arXiv 2512.12818](https://arxiv.org/html/2512.12818v1)
- Project data: `notebooks/evaluation/tender_offers.csv`, `outputs/events.csv`
