"""Step 5 of the brief: checks before anything reaches a client.

Two kinds of check. Narrative checks decide whether the model's wording can be used at all. Record checks decide
whether an item goes straight to the client or waits for an operations reviewer.
"""

from __future__ import annotations

import re
from pathlib import Path

from .event_store import EventState
from .impact import Impact
from .prioritize import implausible_deadline, rights_deadline

_NUMBER = re.compile(r"(?<![\w.])\$?\d[\d,]*(?:\.\d+)?%?")
# Wording that would turn information into advice. "Consideration" is a merger term and an "advisor" is a party, so neither counts.
_ADVICE = re.compile(r"\b(should|shouldn't|recommend\w*|advis(?:e|es|ed|ing)|suggest\w*|consider(?!ation)\w*|ought|attractive|favou?rable|"
                     r"beneficial|opportunity|worthwhile|wise|good idea|we believe|in your best interest|undervalued|overvalued)\b", re.I)
# The model does not know today's date by itself. Saying a future deadline "was" due would tell a client they missed it.
_PAST_DEADLINE = re.compile(r"\b(?:deadline|vote|meeting)\s+(?:date\s+)?(?:was|were)\b", re.I)
_PAST_DUE = re.compile(r"\b(?:were|was)\s+due\b|\b(?:has|have)\s+passed\b", re.I)
# The brief is written to the client and must not expose how it was produced
_WRONG_VOICE = re.compile(r"\bthe client(?:'s|’s)?\b|\bthe record\b(?!\s+date)|\bthe json\b", re.I)


def _numbers(text: str) -> set[str]:
    return {m.group(0).rstrip(",").lstrip("$").replace(",", "") for m in _NUMBER.finditer(text or "")}


def check_narrative(summary: str | None, facts_text: str) -> list[str]:
    """Problems with a drafted summary. An empty list means it can be used."""
    if not summary or not summary.strip():
        return ["empty summary"]
    problems = []
    unknown = sorted(_numbers(summary) - _numbers(facts_text))
    if unknown:
        problems.append("numbers not in the record: " + ", ".join(unknown))
    advice = sorted({m.group(0).lower() for m in _ADVICE.finditer(summary)})
    if advice:
        problems.append("advice wording: " + ", ".join(advice))
    cutoff_passed = re.search(r'"cutoff_passed":\s*true', facts_text) is not None
    if _PAST_DEADLINE.search(summary) or (_PAST_DUE.search(summary) and not cutoff_passed):
        problems.append("wrong tense: deadlines after the brief date are still ahead, so write 'are due' and 'is', not 'were due' or 'was'")
    if cutoff_passed and (re.search(r"\bare\s+due\b", summary, re.I) or not re.search(r"\bcut-?off\b.*\bpassed\b", summary, re.I)):
        problems.append("the BNY cut-off has passed: write 'the BNY cut-off of <date> has passed', not 'are due'")
    # Tender cash only holds if every share is accepted. A sentence without that condition would promise money.
    if re.search(r'"tender_cash":\s*true', facts_text) and re.search(r"\$\d", summary) and not re.search(r"\baccept|\bprorat", summary, re.I):
        problems.append("tender offer: state cash only as what you would receive if all shares tendered are accepted")
    voice = sorted({m.group(0).lower() for m in _WRONG_VOICE.finditer(summary)})
    if voice:
        problems.append("wrong voice: address the reader as 'you' and 'your' and do not mention the record (" + ", ".join(voice) + ")")
    if len(summary.split()) > 70:
        problems.append("too long")
    return problems


def check_record(state: EventState, impact: Impact, tier: str) -> list[dict]:
    """Reasons an item needs a human before it goes out."""
    reasons: list[dict] = []
    f = state.facts

    def add(code: str, detail: str) -> None:
        reasons.append({"code": code, "detail": detail})

    if state.event.action == "rights_issue":
        expiry = f.get("expiration_date") or f.get("election_deadline")
        if implausible_deadline(state):
            add("date_conflict", f"Deadline {rights_deadline(state).value.isoformat()} is well before the first filing "
                                 f"({state.first_filed.isoformat()}), which may be a typo in the source.")
        if expiry and f.get("record_date") and f["record_date"].value > expiry.value:
            add("date_conflict", f"Record date {f['record_date'].value.isoformat()} is after expiration {expiry.value.isoformat()}.")
        if expiry and f.get("effective_date") and f["effective_date"].value < expiry.value:
            add("date_conflict", f"Issuance date {f['effective_date'].value.isoformat()} is before expiration {expiry.value.isoformat()}.")
    if impact.offering_cap_exceeded:
        add("offering_limit", impact.offering_cap_exceeded)
    for c in state.changes:
        # Deadlines get extended. One moving earlier is unusual enough for a person to confirm.
        if c.key in {"expiration_date", "election_deadline"} and c.current < c.previous:
            add("deadline_moved_earlier", f"The deadline moved from {c.previous.isoformat()} to {c.current.isoformat()} in the {c.form} filed {c.filed.isoformat()}.")
    if tier == "action":
        if impact.not_computed_reason and "watchlist" not in impact.not_computed_reason.lower():
            add("impact_missing", impact.not_computed_reason)
        if state.event.action == "rights_issue":
            key = f.get("election_deadline") or f.get("expiration_date")
        elif state.event.action == "tender_offer":
            key = f.get("expiration_date")
        else:
            key = f.get("election_deadline") or f.get("vote_date")
        if key and not key.quote:
            add("no_evidence", f"The deadline has no supporting quote in {key.form} filed {key.filed.isoformat()}.")
    return reasons


class QuoteChecker:
    """Confirms a quote really appears in the filing text, when that text is available locally."""

    def __init__(self, text_dir: str | Path | None) -> None:
        self.text_dir = Path(text_dir) if text_dir else None
        self._cache: dict[str, str | None] = {}

    @staticmethod
    def _squash(s: str) -> str:
        return re.sub(r"\s+", "", s or "")

    def _text(self, accession: str) -> str | None:
        if accession not in self._cache:
            path = self.text_dir / f"{accession}.txt" if self.text_dir else None
            self._cache[accession] = self._squash(path.read_text(encoding="utf-8", errors="ignore")) if path and path.exists() else None
        return self._cache[accession]

    def verified(self, accession: str, quote: str | None) -> bool | None:
        """True or False when the text is available, None when it is not."""
        text = self._text(accession)
        if text is None or not quote:
            return None
        return self._squash(quote) in text
