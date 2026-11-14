"""Rule-based merger dates: find a candidate, give it a role from the wording around it, or return nothing.

A wrong date is the costliest error (BNY demo feedback, October 16), so every rule abstains unless the wording is
explicit, and returns the sentence it used as evidence. Patterns were written from training filings only.

  shareholder_vote_date  "the special meeting will be held on <date>", "held a special meeting ... on <date>".
                         Abstains when the meeting date is a placeholder ("[•], 2026") or when the filing names
                         several different meeting dates without one clearly dominant.
  effective_date         completion wording only ("the merger became effective on <date>", "On <date>, ... merged
                         with and into", "completed the merger on <date>"), and only in filings that report a
                         completion (8-K, SC 13E3/A); proxies and registration statements describe future deals.
  election_deadline      the definition of the election deadline, returned as written ("5:00 p.m., Eastern time,
                         on the date that is five business days prior to ..."): it is usually relative, not a date.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta

import common

MONTH = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)"
DATE = rf"{MONTH}\s+\d{{1,2}},?\s+\d{{4}}"
TIME = r"(\d{1,2}(?::\d{2})?\s*(?:a\.?m\.?|p\.?m\.?|noon)(?:[\s,]+(?:\w+\s+){0,3}?(?:Time|time))?)"
PLACEHOLDER = re.compile(r"\[\s*[•·_ ]*\s*\]|\bon\s*,\s*20\d\d|\[DATE\]|\[•\]", re.I)

MEETING = re.compile(r"\b(?:special|annual|extraordinary\s+general|general|stockholders[’']?|shareholders[’']?)\s+"
                     r"meeting\b", re.I)
HELD = re.compile(r"\b(?:will|shall)\s+be\s+held|\bto\s+be\s+held|\bis\s+scheduled\s+(?:to\s+be\s+held\s+)?(?:for|on)|"
                  r"\bhas\s+been\s+scheduled\s+(?:for|on)|\bheld\b|\b(?:postponed|adjourned)\s+(?:to|until)|"
                  r"\breconvene[ds]?\b", re.I)
COMPLETION = [
    re.compile(rf"(?:merger|mergers|business\s+combination|transaction)s?\s+(?:became|become|was|were|has\s+become)\s+"
               rf"effective\s+(?:on|as\s+of)\s+(?P<date>{DATE})", re.I),
    re.compile(rf"\b(?:completed|consummated|closed)\s+(?:the|its)\s+(?:previously\s+announced\s+)?(?:merger|mergers|"
               rf"business\s+combination)[^.;]{{0,120}}?\bon\s+(?P<date>{DATE})", re.I),
    re.compile(rf"\b(?:merger|mergers|business\s+combination|closing)\s+(?:was|were)\s+(?:completed|consummated)\s+"
               rf"(?:on|as\s+of)\s+(?P<date>{DATE})", re.I),
    re.compile(rf"\bOn\s+(?P<date>{DATE}),?\s+(?:pursuant\s+to[^.;]{{0,160}}?,\s*)?[^.;]{{0,80}}?\b(?:merged\s+with\s+and\s+"
               rf"into|completed\s+the\s+(?:previously\s+announced\s+)?(?:merger|business\s+combination)|consummated\s+the\s+"
               rf"(?:previously\s+announced\s+)?(?:merger|business\s+combination))", re.I),
]
COMPLETION_FORMS = {"8-K", "8-K/A", "SC 13E3/A", "SC 13E3"}
REPORT_FORMS = {"8-K", "8-K/A"}  # report a meeting that already took place
FUTURE_HELD = re.compile(r"\b(?:will|shall)\s+be\s+held|\bto\s+be\s+held|\bis\s+scheduled|\bhas\s+been\s+scheduled|"
                         r"\b(?:postponed|adjourned)\s+(?:to|until)|\breconvene", re.I)
OTHER_ELECTIONS = re.compile(r"redemption|redeem|bonus|deferr|stock\s+option|director|nominat|tax\s+election|"
                             r"section\s+83|withholding", re.I)
ELECTION = re.compile(r"election\s+deadline|deadline\s+for\s+(?:submitting|making|the\s+receipt\s+of)\s+(?:an?\s+)?"
                      r"(?:properly\s+completed\s+)?elections?|elections?\s+(?:form\s+)?must\s+be\s+(?:made|received|"
                      r"submitted)", re.I)


# a full stop that ends a sentence: not the one in "p.m.", "a.m.", "Inc.", "Corp.", "No.", "Co."
SENTENCE_END = re.compile(r"(?<![ap]\.m)(?<!\bInc)(?<!\bCorp)(?<!\bNo)(?<!\bCo)(?<!\bLtd)\.\s+(?=[A-Z“\"(\[])|\n\n")


def sentence(text: str, pos: int, reach: int = 500) -> tuple[int, str]:
    """The sentence around pos (bounded), as (start offset, text with whitespace collapsed)."""
    lo = max(0, pos - reach)
    ends = [m.end() for m in SENTENCE_END.finditer(text, lo, pos)]
    lo = ends[-1] if ends else lo
    hi = min(len(text), pos + reach)
    end = SENTENCE_END.search(text, pos, hi)
    hi = end.start() + 1 if end else hi
    return lo, re.sub(r"\s+", " ", text[lo:hi]).strip()


def fmt(day, time: str | None) -> str:
    out = f"{day.month}/{day.day}/{day.year}"
    if time:
        t = re.sub(r"\s+", " ", time).replace(".", "").replace(",", "").strip()
        t = re.sub(r"\b(am|pm)\b", lambda m: m.group(1).upper(), t, flags=re.I)
        out += f" {t}"
    return out


# ---------------------------------------------------------------- shareholder vote date
def vote_date(text: str, form: str = "", filed: date | None = None) -> tuple[str, str]:
    """Proxies and registration statements announce a future meeting ("will be held"), dated after the filing;
    8-Ks report a meeting already held, dated shortly before the filing."""
    report = form in REPORT_FORMS
    held = HELD if report else FUTURE_HELD
    dates: Counter = Counter()
    times: dict = {}
    evidence: dict = {}
    placeholders = 0
    seen = set()
    for m in MEETING.finditer(text):
        lo, sent = sentence(text, m.start())
        if lo in seen:
            continue
        seen.add(lo)
        if re.search(r"record\s+date", sent, re.I) and not re.search(r"(?:will|to)\s+be\s+held", sent, re.I):
            continue
        for h in held.finditer(sent):
            after = sent[h.end():h.end() + 160]
            if PLACEHOLDER.search(after[:60]):
                placeholders += 1
                break
            d = re.search(rf"\bon\s+(?:\w+,\s+)?({DATE})", after) or re.search(rf"^\W*(?:\w+\s+){{0,6}}?({DATE})", after)
            if d:
                parsed = common.parse_dates(d.group(1))
                if parsed:
                    day = parsed[0][0]
                    if filed and not (filed - timedelta(days=120) <= day <= filed + timedelta(days=5) if report
                                      else filed - timedelta(days=5) <= day <= filed + timedelta(days=365)):
                        break  # an earlier or unrelated meeting
                    dates[day] += 1
                    t = re.search(TIME, after[d.end(): d.end() + 80], re.I)
                    if t and day not in times:
                        times[day] = t.group(1)
                    evidence.setdefault(day, sent[:300])
                break
    if not dates or placeholders >= sum(dates.values()):
        return "", ""
    (top, n), *rest = dates.most_common()
    if rest and n < 0.6 * sum(dates.values()):
        return "", ""  # several different meeting dates and none dominant: leave it to a reviewer
    return fmt(top, times.get(top)), evidence[top]


# ---------------------------------------------------------------- effective date
def effective_date(text: str, form: str, filed: date | None = None) -> tuple[str, str]:
    """Completion wording in a filing that reports a completion, dated within a year before the filing."""
    if form not in COMPLETION_FORMS:
        return "", ""
    dates: Counter = Counter()
    evidence: dict = {}
    for pattern in COMPLETION:
        for m in pattern.finditer(text):
            parsed = common.parse_dates(m.group("date"))
            if parsed and filed and not (filed - timedelta(days=365) <= parsed[0][0] <= filed + timedelta(days=5)):
                continue  # an earlier deal mentioned in the filing
            if parsed:
                dates[parsed[0][0]] += 1
                evidence.setdefault(parsed[0][0], re.sub(r"\s+", " ", m.group(0))[:300])
    if not dates:
        return "", ""
    (top, n), *rest = dates.most_common()
    if rest and rest[0][1] == n:
        return "", ""
    return fmt(top, None), evidence[top]


# ---------------------------------------------------------------- election deadline
TIMING = re.compile(r"business\s+days?|calendar\s+days?|[ap]\.?\s?m\b|\b20\d\d\b|effective\s+(?:time|date)|closing|"
                    r"completion|completed|meeting|announced|prior\s+to|before|after", re.I)


def election_deadline(text: str) -> tuple[str, str]:
    """The timing phrase that defines the deadline, preferring a definition ("the election deadline will be ...")."""
    phrases: Counter = Counter()
    evidence: dict = {}
    for m in ELECTION.finditer(text):
        _, sent = sentence(text, m.start())
        if OTHER_ELECTIONS.search(sent):
            continue  # a redemption, bonus or tax election, not an election of merger consideration
        start = sent.lower().find(m.group(0).lower())
        tail = re.search(r"(?:will\s+be|is|means|shall\s+be|no\s+later\s+than|on\s+or\s+before|prior\s+to)\s+"
                         r"(?P<when>.{8,240})", sent[start:], re.I)
        if not tail:
            continue
        # cut at the end of the timing phrase; "p.m." and "a.m." are not sentence ends
        when = re.split(r"(?<![ap]\.m)\.\s+[A-Z]|;|\(|,\s+with\s+the\s+exact|,?\s+or\s+such\s+other|,\s+and\s+(?:any|if)",
                        tail.group("when"))[0].strip(" ,.")
        if re.search(r"election\s+deadline", when, re.I) or not TIMING.search(when):
            continue  # names the deadline instead of stating it, or has no timing in it
        if re.search(r"not\s+(?:currently\s+)?known|to\s+be\s+announced|has\s+not\s+been\s+determined", when, re.I):
            when = "To be announced: " + when
        key = re.sub(r"\W+", " ", when.lower()).strip()
        definition = bool(re.search(r"election\s+deadline\W{0,4}\s*(?:will\s+be|means|is|shall\s+be)", sent[start:], re.I))
        phrases[key] += 3 if definition else 1
        evidence.setdefault(key, (when, sent[:300]))
    if not phrases:
        return "", ""
    key = phrases.most_common(1)[0][0]
    return evidence[key]


def predict(text: str, form: str, filed: date | None = None) -> dict[str, tuple[str, str]]:
    """field -> (value, evidence sentence); empty value = abstained."""
    return {"shareholder_vote_date": vote_date(text, form, filed), "effective_date": effective_date(text, form, filed),
            "election_deadline": election_deadline(text)}
