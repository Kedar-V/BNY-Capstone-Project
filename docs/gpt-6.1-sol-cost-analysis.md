# GPT-6.1 Sol API Cost Analysis — Filing Document Processing

*Purpose: justify API spend for extracting structured corporate-action fields from SEC filings with **GPT-6.1 Sol** (`gpt-6.1-sol`). Prices as of 2026-09-30 from [OpenAI model docs](https://developers.openai.com/api/docs/models/gpt-6.1-sol) and [pricing](https://developers.openai.com/api/docs/pricing).*

---

## 1. Model & unit prices

| Item | Standard rate |
|---|---|
| Input | **$2.00 / 1M tokens** |
| Cached input | **$0.10 / 1M tokens** |
| Cache writes | **$2.50 / 1M tokens** |
| Output | **$10.00 / 1M tokens** |

| Adjustment | Multiplier |
|---|---|
| Prompt **>272K** input tokens | **2×** input/cache, **1.5×** output (whole request) |
| Fast mode | **2×** Standard |
| Batch / Flex | **0.5×** Standard |
| Regional processing | **+10%** where available |

Context: **1,050,000** input window; **128,000** max output. Reasoning effort: `low` → `max` (default `medium`).

**Work formula (Standard, no cache):**

\[
\text{cost} = \frac{T_{\text{in}}}{10^6}\cdot 2 + \frac{T_{\text{out}}}{10^6}\cdot 10
\]

### vs Claude Opus 5.5

Sources: [OpenAI gpt-6.1-sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [Anthropic Opus 5.5](https://platform.claude.com/docs/en/models/opus-5-5/overview) / [pricing](https://platform.claude.com/docs/en/about-claude/pricing) (2026-09-30).

| | GPT-6.1 Sol | Claude Opus 5.5 | Ratio (Opus / Sol) |
|---|---:|---:|---:|
| Input / 1M | $2.00 | $4.00 | **2.0×** |
| Output / 1M | $10.00 | $20.00 | **2.0×** |
| Cached input / 1M | $0.10 | $0.20 | **2.0×** |
| Batch | 50% off | 50% off | still **2.0×** |
| Context | 1.05M | 1M | ~same |
| Max output | 128K | 128K | same |

Same token mix → **Opus 5.5 costs ~2× Sol** end-to-end. (Claude Sonnet 5 is $2 / $10 — same list price as Sol.)

| Scenario | Sol | Opus 5.5 |
|---|---:|---:|
| Per event (blend ~$0.30 Sol) | ~$0.25–0.40 | **~$0.50–0.80** |
| Mid monthly (~420 events) | **~$110** | **~$220** |
| Mid monthly Batch | ~$55 | **~$110** |
| High monthly (~830 events) | ~$330 | **~$660** |
| Sample pack (250 docs, retrieval) | ~$12 | **~$24** |

**Takeaway for this project:** Sol is the cheaper default for bulk filing extraction; Opus 5.5 is a quality upgrade at **~2× API spend**. Use Opus only where eval shows a clear accuracy lift on hard docs (long OTP / S-4), not for every amendment.

### vs Cursor (IDE usage)

Sources: [cursor.com/docs/models-and-pricing](https://cursor.com/docs/models-and-pricing) (2026-09-30).

**Different product.** Cursor bills **developer agent / chat usage inside the IDE**. This filing pipeline should call **OpenAI/Anthropic APIs directly** (Batch, caching, scripts) — not burn Cursor quota on 5K events/month.

| | Direct OpenAI `gpt-6.1-sol` | Cursor listed **GPT-5.6 Sol** | Cursor **Claude Opus 5.5** |
|---|---:|---:|---:|
| Input / 1M | $2.00 | $4.00 | $4.00 |
| Output / 1M | $10.00 | $20.00 | $20.00 |
| Cached input / 1M | $0.10 | $0.40 | $0.20 |

Cursor’s Other Models pool is charged at those listed rates (provider API price as Cursor publishes it). Note: Cursor currently lists **GPT-5.6 Sol at $4/$20** — **~2×** the OpenAI **gpt-6.1-sol** API we’re costing at $2/$10.

| Cursor plan | Seat $/mo | What you get |
|---|---:|---|
| Pro | $20 | Cursor Models pool + Other Models pool (third-party at API rates) |
| Pro+ | $60 | More included usage |
| Ultra | $200 | Heavier agent users |
| Teams Standard / Premium | $40 / $120 per user | + **$0.25 / 1M tokens** Cursor Token Rate on third-party |

Rough fit of our **mid production** (~$110/mo Sol API or ~$220 Opus) against Cursor:

| If you tried to run mid volume *through Cursor* | What happens |
|---|---|
| Mid Sol-equivalent at Cursor’s **$4/$20** Sol list | **~$220/mo** usage alone (2× our direct Sol estimate) — on top of seat fee |
| Mid Opus 5.5 | **~$220/mo** usage (same as direct Anthropic) + seat + Teams token rate if applicable |
| Pro $20 seat | Included Other Models allowance is small vs production volume → **on-demand** almost immediately |

**Takeaway:** Use Cursor for **building/eval** (notebooks, prompts, agent coding). Cost the **production filing extract** on **direct API** — especially OpenAI Batch at 50% off, which Cursor’s IDE pool does not replace.

### vs Grok 4.7 in Cursor

Source: [cursor.com/docs/models-and-pricing](https://cursor.com/docs/models-and-pricing) (2026-09-30). Grok 4.7 sits in the **Cursor Models** pool (separate from Other Models / OpenAI / Anthropic).

| | Direct OpenAI `gpt-6.1-sol` | Cursor **Grok 4.7** | Cursor **Grok 4.7 Fast** |
|---|---:|---:|---:|
| Input / 1M | $2.00 | **$2.00** | $4.00 |
| Output / 1M | $10.00 | **$6.00** | $12.00 |
| Cache read / 1M | $0.10 | $0.50 | $1.00 |
| Long context | >272K → 2× in / 1.5× out (full request) | >256K → **2×** rates (up to 500k) | >256K Fast → **3×** standard |

| | Sol (direct) | Grok 4.7 (Cursor list) |
|---|---:|---:|
| Output-heavy extract (same tokens) | baseline | **~40% cheaper on output** ($6 vs $10) |
| Input-only (same tokens) | same $2 | same $2 |
| Mid monthly (~420 events, ~$110 Sol) | **~$110** | **~$80–95** (rough; output-weighted) |

**Plan angle:** Grok draws from **Cursor Models** included usage (Pro / Pro+ / Ultra), not the Other Models dollar pool that Sol/Opus burn. So for **IDE / agent work** while building the pipeline, Grok 4.7 is usually the cheaper Cursor pick vs selecting Sol or Opus 5.5.

**For production filing batch:** still prefer **direct OpenAI API** (Batch 50% off, no seat, scripted). Grok-in-Cursor is a build-time option, not the production cost line — and there is no Grok Batch equivalent in our OpenAI cost model.

### Cursor API / SDK (same meter as the IDE)

Cursor’s programmatic surface ([SDK](https://cursor.com/docs/sdk/typescript), Cloud Agents, `/v1/agents`) is billed like IDE agent runs: **token pools at the listed model rates**, not a separate cheap “API SKU.”

| Path | What you pay for Sol-class work | Batch 50% off? |
|---|---|---|
| **OpenAI API** `gpt-6.1-sol` | $2 / $10 | **Yes** |
| **Cursor SDK** + GPT-5.6 Sol | Cursor list **$4 / $20** (Other Models pool) | **No** |
| **Cursor SDK** + Grok 4.7 | $2 / $6 (Cursor Models pool) | **No** |
| **Cursor SDK** + Opus 5.5 | $4 / $20 + Teams **+$0.25/M** if applicable | **No** |

SDK is good for **agents that edit repos / run tools** (CI bots, cloud coding agents). It is a **worse** meter for “send filing text → get JSON fields” at scale: same or higher token price than direct providers, agent overhead (tools/context), and no OpenAI Batch.

**Rule:** Cursor API/SDK ≠ substitute for the extraction API line in this cost analysis.

---

## 2. What we will process

Five corporate-action tracks and their filing packs (same scope as the product brief):

| Event type | Filing documents |
|---|---|
| Tender offers (cash) | Schedule TO, TO-T, TO-I, 14D-9, amendments, Offer to Purchase |
| Exchange offers | Schedule TO, Offer to Exchange, S-4, amendments |
| Rights issues | S-1/S-3, prospectus supplements, 8-K, sometimes Form CB |
| Mergers | S-4, 8-K, proxy statements, merger agreement exhibits, sometimes Schedule TO |
| Conversions | 8-K, S-3/S-4, prospectuses, security agreements / exhibits |

Pipeline assumption for this estimate: **one extraction pass per document** (system + schema prompt ≈ 2K tokens; structured JSON out ≈ 1.5–2.5K tokens). Large Offers to Purchase / S-4s are **chunked or section-retrieved** so we stay under the 272K long-context surcharge.

---

## 3. Token sizes from our sample pack

Source: `data/samples/` (250 HTML filings). Token estimate ≈ `html_bytes / 4`.

| Doc folder | n | Median tokens | Mean tokens | Notes |
|---|---:|---:|---:|---|
| schedule_to | 30 | ~13K | ~16K | Cover + schedules |
| to_t / to_i | 30 ea | ~12–13K | ~16K | |
| amendments | 30 | ~6K | ~17K | Skewed by rare large amends |
| 8k | 30 | ~9K | ~10K | |
| 8k_exhibits | 40 | ~14K | ~30K | |
| 14d9 | 30 | ~129K | ~108K | Heavy |
| offer_to_purchase | 30 | ~59K | ~209K | Heavy; outliers >1M chars → **must chunk** |

Whole sample pack ≈ **13M** raw document tokens (before prompts / chunking).

---

## 4. Unit costs (Standard)

Per-document cost using **median** input + 2K prompt + 1.5K output:

| Document type | ≈ Input tokens | ≈ Cost / doc |
|---|---:|---:|
| Schedule TO / TO-T / TO-I | 14–15K | **$0.04–0.05** |
| Amendment | ~8K | **$0.03** |
| 8-K | ~11K | **$0.04** |
| 8-K exhibit | ~16K | **$0.05** |
| Offer to Purchase (median) | ~61K | **$0.14** |
| 14D-9 (median) | ~131K | **$0.28** |
| S-4 / long prospectus (assumed ~80K) | ~82K | **~$0.18** |
| Proxy (assumed ~60K) | ~62K | **~$0.14** |

**Illustrative cost per event** (sum of typical docs, 1 pass each):

| Event type | Typical pack | ≈ Cost / event |
|---|---|---:|
| Cash tender | TO + 14D-9 + OTP + amendment | **~$0.45–0.55** |
| Exchange | TO + S-4/OTP + amendment | **~$0.25–0.35** |
| Rights | S-1/S-3 (+ supp) + 8-K | **~$0.15–0.20** |
| Merger | S-4 + 8-K + proxy + exhibit | **~$0.35–0.45** |
| Conversion | 8-K + S-3/S-4 + exhibit | **~$0.20–0.25** |

Blend across the five types ≈ **$0.25–0.40 / event** on Standard — in line with the ROI placeholder \(v = \$0.25\) in `docs/roi-framework-v1.md`. With **Batch API (50% off)** → **~$0.13–0.20 / event**.

---

## 5. Scenario roll-up

Assumptions for scaled rows: ~20K doc tokens + 2K prompt in, 2K out, 4 docs / event, 1 pass, Standard unless noted.

| Scenario | Volume | Est. API cost |
|---|---|---:|
| Capstone sample pack (retrieval budget ~15K tok/doc) | 250 docs | **~$12** |
| Capstone sample pack (full HTML, naive) | 250 docs | **~$30** |
| MVP build / eval corpus | 500 events × 4 docs | **~$130** |
| Year-1 production (mid) | 5,000 events × 4 docs | **~$1,300** |
| Same, **Batch API** | 5,000 events | **~$650** |
| Year-1 production (high) | 10,000 events × 5 docs | **~$4,000** |
| Stress: 2 passes (extract + verify) @ 5K events | 5,000 × 2 | **~$2,600** |

### Monthly total (production)

Annual ÷ 12, same assumptions (~$0.26/event Standard; Batch = ½):

| Monthly volume | Events / mo | Standard $/mo | Batch $/mo |
|---|---:|---:|---:|
| Low | ~200 (~2.4K / yr) | **~$50** | **~$25** |
| Mid (base) | ~420 (~5K / yr) | **~$110** | **~$55** |
| High | ~830 (~10K / yr) | **~$330** | **~$165** |
| Stress (100K / yr) | ~8,300 | **~$2,100** | **~$1,050** |

**Base planning number: ~$110 / month Standard** (~$55 Batch) at ~420 events/month.

Even at **100,000 events / year** with a 4-doc pack on Standard, API variable cost stays on the order of **~$25K / year (~$2.1K / month)** — still small vs. ops FTE load in the ROI model (\(c \approx \$100\text{K}\) per FTE; minutes of manual handling per event).

---

## 6. Cost justification (why this spend is fine)

1. **Variable cost is tiny vs. labor.** At ~$0.30/event Standard, **~3,000 events ≈ $900**. One ops FTE hour at a fully loaded ~$60/hr already exceeds processing dozens of filings. Automating even a fraction of \(\tau_M / \tau_V\) minutes pays for the API many times over (see ROI framework §1–2).

2. **Sol is the right price/quality tier.** GPT-6.1 Sol is positioned as near-Astra quality for complex professional extraction at **$2 / $10** — materially cheaper than Astra ($10 / $50 short-context on the same pricing page) while still supporting long context, structured outputs, and high reasoning effort for messy EDGAR text.

3. **Spend is controllable.**
   - Batch offline backfills → **50% off**.
   - Stable schema/system prompts → **cached input at $0.10/M**.
   - Chunk / retrieve sections instead of dumping full OTPs → avoid **>272K** 2× surcharge and cut input tokens.
   - Cap pilot spend: sample pack is **tens of dollars**, not thousands.

4. **Fits the existing ROI variable \(v\).** Measuring ~$0.25–0.40/event validates (or slightly raises) the Base \(v\) without changing the NPV story; Batch brings \(v\) toward the optimistic side.

5. **Error / STP upside dominates API line item.** In the ROI model, labour + error benefits (\(B^L + B^E\)) are measured in **hundreds of thousands to millions**; API tokens are a small component of \(C_t = Kk + N_t a_t v + G\).

---

## 7. Recommended operating posture

| Phase | Mode | Budget cue |
|---|---|---|
| Capstone / eval | Standard, low–medium reasoning | **<$50** for sample pack; **~$100–200** for MVP corpus |
| Offline backfill | **Batch** | ~½ of Standard |
| Live / low-latency | Standard (+ cache schema) | Monitor $/event; alert if >$1 |
| Rare mega-docs | Chunked extract, not single 272K+ call | Avoid long-context multiplier |

---

## 8. Sources & caveats

- Prices: [developers.openai.com/api/docs/models/gpt-6.1-sol](https://developers.openai.com/api/docs/models/gpt-6.1-sol), [developers.openai.com/api/docs/pricing](https://developers.openai.com/api/docs/pricing) (retrieved 2026-09-30).
- Token sizes from local `data/samples/` HTML; S-4 / proxy / S-1 sizes are **assumed** until those folders are measured the same way.
- Does **not** include OCR of scanned PDFs, tool-call fees, or retries. Reasoning tokens (if billed as output) can raise cost — re-measure once the extraction harness logs real `usage`.
- Replace scenario volumes with BNY-confirmed \(N_1\) when available; plug measured \(v\) back into `docs/roi-framework-v1.md`.
