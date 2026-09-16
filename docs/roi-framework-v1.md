# ROI Framework v1 — Corporate Action AI (formula-first)

*Status: framework for review. Numbers are placeholders to be replaced once the team and BNY confirm inputs. Companion workbook: `BNY_Corporate_Action_AI_ROI_Model_v1.xlsx`; longer notes in `roi-model-v1.md`. Formulas are written in LaTeX; a rendered PDF is attached alongside.*

## 0. The question

Spend $K$ now to build the system; does what it saves over 5 years justify $K$?

$$
\text{NPV} = \sum_{t=0}^{5} \frac{\text{Net}_t}{(1+r)^t} \;\ge\; 0
$$

Everything below defines $\text{Net}_t$.

## 1. Baseline: manual work that exists today (year $t = 1,\dots,5$)

| Symbol | Meaning |
|---|---|
| $N_t$ | Event notifications in scope in year $t$; $N_1$ = year-1 volume, $g$ = annual growth |
| $m$ | Share of events that are mandatory ($1-m$ = voluntary) |
| $s_M,\ s_V$ | Current STP rate for mandatory / voluntary events (share already fully automated) |
| $\tau_M,\ \tau_V$ | Minutes of human handling per manually processed mandatory / voluntary event |
| $h$ | Productive hours per FTE per year |
| $c$ | Fully loaded annual cost per operations FTE |

$$
N_t = N_1\,(1+g)^{\,t-1}
$$

$$
H_t = \frac{N_t}{60}\Big[\, m\,(1-s_M)\,\tau_M \;+\; (1-m)(1-s_V)\,\tau_V \,\Big]
\qquad\text{(manual hours)}
$$

$$
F_t = \frac{H_t}{h} \qquad\text{(manual FTE)},\qquad
L_t = F_t \cdot c \qquad\text{(addressable labour cost)}
$$

## 2. What the AI changes

| Symbol | Meaning | Where the number comes from |
|---|---|---|
| $a_t$ | Adoption share in year $t$ (ramp from 0 to 1) | Rollout plan |
| $\alpha_M,\ \alpha_V$ | Share of currently manual mandatory / voluntary events the AI fully automates | Our eval harness: share of events passing the confidence threshold and validated correct |
| $\beta$ | Handling-time reduction on events that still need a human | Our eval / user test: review time with vs without AI pre-population |
| $\rho$ | Realisation rate: share of released hours that becomes real savings or avoided hiring | BNY ops / finance |

Manual hours remaining with the AI (non-adopted events keep full time; adopted events are either automated away or handled faster):

$$
\begin{aligned}
H'_t = \frac{N_t}{60}\Big\{\;
& m\,(1-s_M)\,\tau_M \big[(1-a_t) + a_t(1-\alpha_M)(1-\beta)\big] \\
+\; & (1-m)(1-s_V)\,\tau_V \big[(1-a_t) + a_t(1-\alpha_V)(1-\beta)\big]
\;\Big\}
\end{aligned}
$$

$$
\Delta H_t = H_t - H'_t,
\qquad
B^{L}_t = \frac{\Delta H_t}{h}\cdot c \cdot \rho
\qquad\text{(labour benefit)}
$$

Post-AI STP rate is derived, never assumed:

$$
s'_{M,t} = 1 - (1-s_M)\,(1 - a_t\,\alpha_M), \qquad
s'_{V,t} = 1 - (1-s_V)\,(1 - a_t\,\alpha_V)
$$

## 3. Error benefit

| Symbol | Meaning |
|---|---|
| $E$ | Baseline annual cost of corporate-action errors and losses in scope |
| $\delta$ | Share of that cost rooted in data sourcing / validation (the part the AI touches) |
| $\varepsilon$ | Share of the data-rooted cost the AI eliminates at full adoption |

$$
B^{E}_t = E \cdot \delta \cdot \varepsilon \cdot a_t
$$

## 4. Costs

| Symbol | Meaning |
|---|---|
| $K$ | One-time build and integration cost (year 0) |
| $k$ | Annual run and maintenance, as a share of $K$ |
| $v$ | AI variable cost per event processed (LLM tokens, OCR, verification passes) |
| $G$ | Annual governance, model-risk, platform and licence cost |

$$
C_0 = K, \qquad
C_t = K\,k \;+\; N_t\,a_t\,v \;+\; G \quad (t = 1,\dots,5)
$$

## 5. Outputs

$$
\text{Net}_0 = -K, \qquad
\text{Net}_t = B^{L}_t + B^{E}_t - C_t
$$

$$
\text{NPV} = \sum_{t=0}^{5} \frac{\text{Net}_t}{(1+r)^t},
\qquad
\text{DF}_t = \frac{1}{(1+r)^t}
$$

$$
\text{Payback} = \text{first } t \text{ with } \sum_{i=0}^{t} \text{Net}_i \ge 0
\quad\text{(interpolated within the year)}
$$

$$
\text{IRR} = r^{*} \text{ such that } \sum_{t=0}^{5} \frac{\text{Net}_t}{(1+r^{*})^t} = 0
$$

$$
\text{ROI}_{5y} = \frac{\sum_{t=1}^{5}\big(B^{L}_t + B^{E}_t\big) - \sum_{t=0}^{5} C_t}{\sum_{t=0}^{5} C_t}
\qquad\text{(undiscounted)}
$$

Break-even build cost — the most that could be spent on the build before NPV reaches zero (the run cost scales with $K$, hence the denominator):

$$
K^{*} = K + \frac{\text{NPV}}{1 + k \sum_{t=1}^{5} \text{DF}_t}
$$

Cost per event, before and after:

$$
\text{CPE}_{\text{before}} = \frac{L_1}{N_1},
\qquad
\text{CPE}_{\text{after}} = \frac{\dfrac{H'_5}{h}\,c \;+\; N_5\,a_5\,v}{N_5}
$$

Cost per event, payback and break-even build cost are the three numbers to use with a non-technical audience.

## 6. Input register — what is known, what must be filled

| Input | Status | Current placeholder (Base) | Owner |
|---|---|---|---|
| $N_1$ volume in scope | **BNY to confirm** (order of magnitude) | 1,000,000 | Team → BNY |
| $g$ growth | Benchmark (Broadridge/VX +25% YoY, haircut) | 10% | Team |
| $m$ mandatory share | Benchmark (DTCC ~80%) | 80% | Team |
| $s_M,\ s_V$ current STP | Benchmark (voluntary ~40%); BNY can refine | 80% / 40% | Team → BNY |
| $\tau_M,\ \tau_V$ minutes per manual event | **No public source — BNY to confirm** | 20 / 60 | BNY |
| $h$ productive hours | Standard constant | 1,600 | Team |
| $c$ cost per FTE | Benchmark (US median base $111.5k; offshore blend) | $100,000 | Team → BNY |
| $E$ error cost in scope | **BNY to confirm** ($2m or $10m?) | $5,000,000 | BNY |
| $\delta$ data-rooted share | Benchmark (ISSA >2/3, VX 56–67%) | 60% | Team |
| $a_t$ ramp | Rollout plan | 25 / 60 / 90 / 100 / 100% | Team |
| $\alpha_M,\ \alpha_V$ automation shares | **From our eval harness** | 60% / 35% | Team (technical) |
| $\beta$ handling-time reduction | **From our eval / user test** | 25% | Team (technical) |
| $\varepsilon$ error elimination | Benchmark (ISSA up to 87%, haircut) | 50% | Team |
| $\rho$ realisation | BNY finance convention | 70% | BNY |
| $K$ build cost | Estimate from scope; TEI comparables $1–15m | $5,000,000 | Team → BNY |
| $k$ run share | Benchmark 15–25% | 20% | Team |
| $v$ cost per event | Measured from our pipeline (tokens × price × passes) | $0.25 | Team (technical) |
| $G$ governance / platform | BNY convention | $500,000 | BNY |
| $r$ discount rate | BNY hurdle rate | 10% | BNY |

Bold rows are the ones the framework cannot settle without BNY or our own measurements; they are also the top of the sensitivity ranking.

## 7. Scenario and sensitivity rules

Inputs split into two groups. The operating profile ($N, g, m, s, \tau, h, c, E, \delta, r$) describes the operation and is held fixed across scenarios. The bet ($\alpha, \beta, \varepsilon, \rho, K, k, v, G, a_t$) is what Conservative / Base / Optimistic vary. Every input, both groups, is flexed one at a time in the tornado (NPV at its low and high value, all else at Base); swing size ranks which inputs to validate first. Vendor claims are haircut by roughly half before entering Base.

## 8. Finance terms used above (for non-finance readers)

**FTE** — full-time equivalent; two people at half time = 1 FTE. **Fully loaded cost** — salary plus benefits, tax, office, tooling; typically 1.4–1.6× base salary. **STP** — straight-through processing; an event handled end-to-end by systems with no human touch. **Discount rate $r$** — a dollar next year is worth less than a dollar today; $r$ is the annual rate used to shrink future amounts (10% means each year's money counts roughly 10% less). **NPV** — net present value; all future net cash flows shrunk back to today's dollars, minus the upfront spend; positive means worth doing. **IRR** — internal rate of return; the annual return rate the project effectively earns, comparable with a company's hurdle rate. **Payback** — years until cumulative savings equal cumulative spend. **Realisation rate** — hours freed up are not automatically dollars saved; only the share that leads to not hiring or redeploying counts.

## 9. Explicitly excluded (add as separate lines later, never inside the drivers)

Client-revenue upside, regulatory-penalty avoidance, working-capital effects of faster entitlement payment, industry-scale extrapolation from the $58bn figure.
