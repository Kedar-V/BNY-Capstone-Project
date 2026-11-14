"""Temporal NER for merger dates: a date tagger finds every date and time expression in the learned windows, then
the same role wording as date_rules.py decides what each one is, or nothing.

Model: satyaalmasian/temporal_tagger_BERT_tokenclassifier (the tagger tried on tender offers in
scripts/eval_temporal_tagger_dates.py). Unlike a date pattern it also tags relative and approximate expressions
("the second half of 2026", "five business days"), so it is tried for expected_closing and election_deadline too.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import date, timedelta

import common
import date_rules
from window_selection import Selector

MODEL_ID = "satyaalmasian/temporal_tagger_BERT_tokenclassifier"
EXPECT = re.compile(r"\b(?:expect|anticipat|currently\s+(?:expect|anticipat)|target)\w*", re.I)
CLOSE = re.compile(r"\b(?:clos(?:e|ing)|complet(?:e|ion|ed)|consummat\w+)\b", re.I)
COMPLETED = re.compile(r"became\s+effective|\bcompleted\b|\bconsummated\b|merged\s+with\s+and\s+into", re.I)
_tagger = None


def tagger():
    global _tagger
    if _tagger is None:
        from transformers import pipeline
        _tagger = pipeline("token-classification", model=MODEL_ID, aggregation_strategy="simple")
    return _tagger


def timex(chunk: str) -> list[tuple[int, int, str]]:
    """(start, end, label) of date/time/duration expressions in a ~900-character chunk."""
    spans = []
    for ent in tagger()(chunk):
        label = (ent.get("entity_group") or ent.get("entity") or "").upper()
        if any(k in label for k in ("DATE", "TIME", "DURATION")):
            spans.append((int(ent["start"]), int(ent["end"]), label))
    # merge pieces of one expression split by the tokenizer
    merged: list[list] = []
    for s, e, label in sorted(spans):
        if merged and s - merged[-1][1] <= 2:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e, label])
    return [(s, e, label) for s, e, label in merged]


def _dominant(counter: Counter):
    if not counter:
        return None
    (top, n), *rest = counter.most_common()
    if rest and n < 0.6 * sum(counter.values()):
        return None
    return top


def predict(text: str, form: str, filed: date | None, windows: list[tuple[int, str]]) -> dict[str, tuple[str, str]]:
    report = form in date_rules.REPORT_FORMS
    held = date_rules.HELD if report else date_rules.FUTURE_HELD
    vote, effective, closing, election = Counter(), Counter(), Counter(), Counter()
    evidence: dict = {}
    for _, chunk in windows:
        for s, e, _label in timex(chunk):
            phrase = re.sub(r"\s+", " ", chunk[s:e]).strip(" ,.")
            before = chunk[max(0, s - 160):s]
            around = chunk[max(0, s - 200):min(len(chunk), e + 120)]
            days = common.parse_dates(phrase)
            day = days[0][0] if days else None
            if day and date_rules.MEETING.search(around) and held.search(before):
                ok = not filed or (filed - timedelta(days=120) <= day <= filed + timedelta(days=5) if report
                                   else filed - timedelta(days=5) <= day <= filed + timedelta(days=365))
                if ok:
                    vote[day] += 1
                    evidence.setdefault(("vote", day), around)
            if day and form in date_rules.COMPLETION_FORMS and COMPLETED.search(around):
                if not filed or filed - timedelta(days=365) <= day <= filed + timedelta(days=5):
                    effective[day] += 1
                    evidence.setdefault(("effective", day), around)
            if not day and EXPECT.search(before[-120:]) and CLOSE.search(around) and re.search(r"20\d\d|quarter|half|year",
                                                                                               phrase, re.I):
                key = phrase.lower()
                closing[key] += 1
                evidence.setdefault(("closing", key), (phrase, around))
            if re.search(r"election\s+deadline", around, re.I) and not date_rules.OTHER_ELECTIONS.search(around):
                key = phrase.lower()
                election[key] += 1
                evidence.setdefault(("election", key), (phrase, around))
    out = {}
    top = _dominant(vote)
    out["shareholder_vote_date"] = (date_rules.fmt(top, None), evidence[("vote", top)]) if top else ("", "")
    top = _dominant(effective)
    out["effective_date"] = (date_rules.fmt(top, None), evidence[("effective", top)]) if top else ("", "")
    top = _dominant(closing)
    out["expected_closing"] = evidence[("closing", top)] if top else ("", "")
    top = _dominant(election)
    out["election_deadline"] = evidence[("election", top)] if top else ("", "")
    return out


def predict_all(accs: list[str], forms: dict, filed: dict) -> dict:
    selector = Selector.load()
    out = {}
    for n, acc in enumerate(accs, 1):
        text = common.filing_text(acc)
        out[acc] = predict(text, forms[acc], filed[acc], selector.select(text, per_field=5, max_windows=50))
        if n % 10 == 0:
            print(f"temporal NER {n}/{len(accs)}", flush=True)
    return out
