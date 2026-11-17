# Presentation guidelines: BNY capstone decks

How to build and edit slides for the Corporate Action Intelligence project. These reflect Aesha's feedback across the class deck (Oct 2026) and the weekly BNY update decks. Follow them unless she asks otherwise.

## 1. Know the audience first

| Deck | Audience | Shape |
|---|---|---|
| **Class presentation** | Students who know nothing about BNY or finance but can follow technical work. Graded on the CAP2027 rubric. | ~15 slides for 15 minutes, including a 3–4 minute live demo. |
| **Weekly BNY update** | BNY AI Hub and product owners who know corporate actions well. | Fewer than 5-10 slides: what we're working on, framed as responding to their latest feedback. |

- For the class, set the stage before the problem: who BNY is (a custodian that sits between companies and investors) and what a corporate action is, explained simply and visually.
- For the class, cover the rubric: problem and scope, progress, technical approach with evidence, impact, plan and limitations, and a clear narrative.
- For BNY, use their own language and priorities (for example dates, mandatory/voluntary, free-text standardization). Mirror their feedback accurately (see §6).



## 2. Brand, colour and type

- **Colours: BNY palette only.** Navy `#04243C`, teal `#2B9CAE`, light teal `#CFE6E9`, slate text `#475569`, background `#EEEEEE`, card border sand `#D8CDB8`, white cards.
- **Duke Blue is the only extra colour allowed:** Duke Royal Blue `#00539B` and Duke Navy `#012169`.
- **Never** add other colours: no yellow, red, green or multi-colour "category" tints.
- **Progressions use stepped solid colours, not gradient fills.** Each element in a row gets one solid colour, and the colours step across the row (BNY teal → Duke Royal Blue → Duke Navy). Don't blend a gradient inside a single shape.
- **Font: Helvetica Neue** for everything, including new text added to existing decks. Keep existing sizes, weights and colours when changing fonts.
- Draw charts in the deck's font too, so they don't look pasted in.
- **No section label** in the top-left corner above titles, and **no "BNY" footer text** bottom-left.

## 3. Visual style: not "typical Claude slides"

- **Less text, more visual.** One message per slide. Prefer diagrams, icons, real documents and charts over bullets. If a card needs a sentence of explanation, put that sentence in the speaker notes instead.
- **Don't use the same card style on every slide.** Vary the treatment between slides (soft rounded with shadow, flat rounded, one snipped corner, strong rounding with a teal outline, square tiles) so the deck doesn't look templated.
- **Avoid generic devices:** no full-width navy "GOAL:" banners, no accent stripes, no rows of identical boxes for their own sake.
  - Show a goal through the design instead, for example as the destination column that the parts flow into.
- **Icons:** Lucide line icons (ISC licence), white inside solid circular badges. Keep the icon source SVGs in `capstone-presentation/icons/`.
- **Real artefacts beat abstractions:** for example the actual Eventbrite proxy pages with the $4.50 price highlighted, and a page-grid of the whole filing. A click animation that fades from the document to the chart is fine.
- **Keep it simple when asked:** remove decorative extras (fact tiles, supporting grey sub-lines) rather than shrinking them.
- **Text must fit:** keep short labels on one line when boxes are sized for one line. Check that nothing wraps mid-word or overflows.
-- **No page numbers:** do not include page numbers on each slide.

## 4. Titles and charts

- **Titles state the takeaway** (active titles) where the slide makes a claim, but stay broad and defensible.
  - Example: "Corporate-action filings can run longer than a novel", not "One in three filings…".
- **Not every slide needs an active title.** Research, method and "what we're doing" slides get a descriptive title that says what we're working on, e.g. "Research: edge cases in linking filings".
- **Charts follow the course's explanatory-figure rules:**
  - clear axes and labels
  - direct labels instead of legends where possible
  - one highlight colour against muted context
  - no distorting chart types (no 3D, no pies for comparisons)
  - built in matplotlib or seaborn
- Mark conceptual diagrams **"Illustrative, not measured."**
- Keep chart code reproducible (`make_figures.py`, `make_document_figures.py`) and in sync with the numbers on the slides.

## 5. Accuracy rules (non-negotiable)

- **Never generalise from a sample.** Say "in our sample" or describe the range; don't state population rates.
- **Verify every number against the data before it goes on a slide,** and re-check when teammates update the data. If chart data and slide numbers diverge, keep them consistent and flag it.
- **Don't misread failures as findings.** Example: zero-record filings were mostly API timeouts, not "non-mergers". Remove a claim entirely if it turns out to be wrong.
- **Coverage is not accuracy.** "LLM found a value" ≠ "value is correct". The LLM's self-rated quote scores are a triage signal, not accuracy.
- **Limitations should span the pipeline,** not only the ground-truth process. Leave out limitations that only affect the one-off LLM labelling run, such as long filings timing out.

## 6. Wording preferences

- Say **"LLM"**, never "StackAI".
- Don't frame the four parts of the approach as **"deliverables"**. They're connected parts of one process: "How we tackle it".
- Free-text standardization means **consistent, client-ready event descriptions built from extracted key facts**. That's BNY's biggest pain point: staff write these by hand, which is subjective, slow and inconsistent. Don't reduce it to "AI-drafted text".
- **Next steps:**
  - no specific dates, months or deadlines, since scope will change with BNY feedback;
  - no task owners or assignments;
  - include downstream tasks, and event tracking via **RAG or Hindsight**.
- Next-step tags are short: "human review of a sample" rather than "two-reviewer check", and "check with BNY experts" (or "BNY's subject matter experts").
- Acknowledge that BNY's process is proprietary: we work from public SEC filings and their feedback.

## 7. Speaker notes

- **Plain spoken script only:** just the words to say, in short conversational paragraphs.
- **No cues:** no "PURPOSE / SAY / ON SCREEN / TRANSITION", no timings, no "point to" or "click" instructions.
- **12 pt** font, regular weight.
- The last line of each slide's script leads naturally into the next slide.
- The closing slide can include short prepared answers to likely questions, written as plain Q&A.
- The facts in the notes must match the slides exactly.
- Keep the full script within the time limit (~140 words per minute, leaving room for the demo).

## 8. Working on the files

- **Always edit the latest file Aesha points to.** She also edits in Keynote and Google Slides, so her copy may differ from the generated one.
  - Preserve her edits.
  - Never rebuild from an older script over her changes.
- **Only change what was asked.** If she asks for notes, don't touch slide content.
- **Before saving over a file,** confirm it hasn't changed since you read it, and keep a backup.
- **Visual QA every change:**
  - Render with LibreOffice; it can't load Helvetica/Helvetica Neue, so preview a copy with Arial substituted, since the widths match.
  - Check for overflow, wrapping, alignment and overlap.
- Keynote files: change presenter notes through AppleScript, addressing the document by its file path rather than "front document".

## 9. Class deck structure that worked

1. Title
2. Agenda: a visual journey of the stops
3. BNY's role: companies → BNY (custodian) → clients
4. What a corporate action is (Eventbrite example)
5. The problem: the real filing, then a click to the length chart
6. Our approach: four connected parts leading to the goal
7. Pipeline, with built / next / prototype status
8. Methods: rules vs GLiNER vs LLM vs human, on a cost-vs-context axis
9. Data: we build our own labelled set (search → download → label)
10. Evidence: one real record with its quotes
11. Evaluation: before/after deployment lanes, and the goal of LLM-level accuracy at lower cost
12. Live demo
13. Limitations: titles plus short "Next" tags
14. Next steps: verify, track events (RAG/Hindsight), downstream tasks
15. Impact: hub of reusable tools
16. Questions
