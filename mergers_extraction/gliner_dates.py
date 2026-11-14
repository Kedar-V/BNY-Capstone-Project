"""Dates as "GLiNER proposes, checks decide": the fine-tuned GLiNER's date spans (gliner_candidates.py, learned
windows), kept only if they pass checks that do not depend on how a filing words things.

Checks (shared with date_rules.py, but here they only accept or reject GLiNER's spans; no wording pattern finds
the date):
  - it is a calendar date, and not a placeholder such as "[•], 2026"
  - it fits the filing: an 8-K reports a meeting held up to 120 days before it; a proxy or S-4 announces one up to a
    year ahead. An effective date is only taken from a filing that reports a completion, dated within the year
    before the filing
  - its sentence is about the right event: a meeting for the vote date; completion ("completed", "became
    effective", "consummated", "closed") for the effective date; a consideration election (not a redemption or
    tax election) for the election deadline
Among the spans that pass, GLiNER's scores are added up per date; the top date must hold at least 60% of the total,
otherwise the field is left blank for a reviewer.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta

import common
import date_rules as dr
import gliner_candidates

DONE = re.compile(r"\b(?:completed|consummated|closed|became\s+effective|become\s+effective|was\s+effective|"
                  r"effective\s+as\s+of|merged\s+with\s+and\s+into)\b", re.I)
ELECTION_CONTEXT = re.compile(r"\belect(?:ion|ing|s)?\b", re.I)


def _sentence(c: dict) -> str:
    """The sentence the span sits in, from the candidate's surrounding text (the span starts 200 characters in)."""
    ctx = c["context"]
    pos = min(200, len(ctx))
    return dr.sentence(ctx, pos, reach=200)[1]


def _time_after(c: dict) -> str | None:
    ctx = c["context"]
    after = ctx[200 + len(c["value"]):200 + len(c["value"]) + 80]
    t = re.search(dr.TIME, c["value"] + " " + after, re.I)
    return t.group(1) if t else None


def _vote_ok(day: date, sent: str, form: str, filed: date | None) -> bool:
    if not dr.MEETING.search(sent):
        return False
    if re.search(r"record\s+date", sent, re.I) and not re.search(r"(?:will|to)\s+be\s+held", sent, re.I):
        return False
    if filed is None:
        return True
    if form in dr.REPORT_FORMS:
        return filed - timedelta(days=120) <= day <= filed + timedelta(days=5)
    return filed - timedelta(days=5) <= day <= filed + timedelta(days=365)


def _effective_ok(day: date, sent: str, form: str, filed: date | None) -> bool:
    if form not in dr.COMPLETION_FORMS or not DONE.search(sent):
        return False
    return filed is None or filed - timedelta(days=365) <= day <= filed + timedelta(days=5)


def _deadline_ok(day: date | None, sent: str, filed: date | None) -> bool:
    if not ELECTION_CONTEXT.search(sent) or dr.OTHER_ELECTIONS.search(sent):
        return False
    return day is None or filed is None or day >= filed - timedelta(days=5)


def _vote(cands: list[dict], form: str, filed: date | None) -> tuple[str, str]:
    weight, times, evidence = defaultdict(float), {}, {}
    placeholder_weight = 0.0
    for c in cands:
        sent = _sentence(c)
        if dr.PLACEHOLDER.search(c["value"]) or dr.PLACEHOLDER.search(c["context"][200:200 + len(c["value"]) + 40]):
            placeholder_weight += c["score"]
            continue
        parsed = common.parse_dates(c["value"])
        if not parsed or not _vote_ok(parsed[0][0], sent, form, filed):
            continue
        day = parsed[0][0]
        weight[day] += c["score"]
        times.setdefault(day, _time_after(c))
        evidence.setdefault(day, sent[:300])
    return _pick(weight, times, evidence, placeholder_weight)


def _effective(cands: list[dict], form: str, filed: date | None) -> tuple[str, str]:
    weight, evidence = defaultdict(float), {}
    for c in cands:
        parsed = common.parse_dates(c["value"])
        sent = _sentence(c)
        if parsed and _effective_ok(parsed[0][0], sent, form, filed):
            weight[parsed[0][0]] += c["score"]
            evidence.setdefault(parsed[0][0], sent[:300])
    return _pick(weight, {}, evidence, 0.0)


def _deadline(cands: list[dict], filed: date | None) -> tuple[str, str]:
    """Deadlines are often relative ("5:00 p.m., five business days before closing"), so a span passes with or
    without a calendar date; the most-supported wording wins."""
    weight, evidence, shown = defaultdict(float), {}, {}
    for c in cands:
        parsed = common.parse_dates(c["value"])
        sent = _sentence(c)
        day = parsed[0][0] if parsed else None
        if dr.PLACEHOLDER.search(c["value"]) or not _deadline_ok(day, sent, filed):
            continue
        if not day and not dr.TIMING.search(c["value"]):
            continue
        key = day or re.sub(r"\W+", " ", c["value"].lower()).strip()
        weight[key] += c["score"]
        evidence.setdefault(key, sent[:300])
        shown.setdefault(key, dr.fmt(day, _time_after(c)) if day else re.sub(r"\s+", " ", c["value"]).strip())
    if not weight:
        return "", ""
    top = max(weight, key=weight.get)
    if weight[top] < 0.6 * sum(weight.values()):
        return "", ""
    return shown[top], evidence[top]


def _pick(weight, times, evidence, placeholder_weight) -> tuple[str, str]:
    if not weight or placeholder_weight >= sum(weight.values()):
        return "", ""
    top = max(weight, key=weight.get)
    if weight[top] < 0.6 * sum(weight.values()):
        return "", ""  # several dates and none dominant
    return dr.fmt(top, times.get(top)), evidence[top]


def predict_all(accs: list[str], model: str, forms: dict, filed: dict) -> dict:
    out = {}
    for acc, cands in gliner_candidates.load(accs, model).items():
        by = defaultdict(list)
        for c in cands:
            by[c["field"]].append(c)
        out[acc] = {"shareholder_vote_date": _vote(by["shareholder_vote_date"], forms[acc], filed[acc]),
                    "effective_date": _effective(by["effective_date"], forms[acc], filed[acc]),
                    "election_deadline": _deadline(by["election_deadline"], filed[acc])}
    return out
