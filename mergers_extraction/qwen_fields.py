"""Qwen3 4B (local, through Ollama) for the fields a span model cannot produce: formula exchange ratios, the
election deadline, summaries (conditions, options, qualifications), event status and consideration type.

Qwen reads only selected parts of the filing, not the whole filing: the learned windows (window_selection.py) plus
the original keyword windows, which cover conditions and elections. It answers in the ground truth's short format,
as JSON. Responses are cached in outputs/methods/qwen_cache.jsonl so an interrupted run resumes.

Needs Ollama running locally (`ollama serve`) with the model pulled (`ollama pull qwen3:4b`).
"""
from __future__ import annotations

import json
import re
import time
import urllib.request

import common
from window_selection import Selector

MODEL = "qwen3:4b"
URL = "http://localhost:11434/api/chat"
MAX_CHARS = 32_000  # about 8,000 tokens of filing text
CACHE = common.OUTPUTS / "methods" / "qwen_cache.jsonl"

PROMPT = """You extract merger terms from excerpts of one SEC filing. Use only the excerpts. Do not guess.
Return one JSON object with exactly these keys. Use null when the excerpts do not state the value.
Keep values short: no explanations, no labels.

- stock_exchange_ratio: acquirer shares received for one share of the target security, e.g. "0.400 shares of Cliffs common stock per share". For a formula, state it briefly as written. "No stock consideration" if holders receive no stock.
- shareholder_vote_date: date of the meeting where holders vote on the merger, as M/D/YYYY with the time if stated, e.g. "6/11/2026 10:00 AM Eastern Time". null if the date is blank or a placeholder such as "[•]".
- effective_date: the date the merger was completed or became effective, as M/D/YYYY. null unless the excerpts say it has happened.
- election_deadline: the deadline for holders to choose their consideration, as written briefly, e.g. "5:00 PM Eastern Time, five business days before closing". null if holders have no election.
- event_status: exactly one of "Announced", "Pending", "Amended", "Completed", "Terminated", "Withdrawn".
- consideration_type: exactly one of "Cash", "Stock", "Mixed cash and stock", "Elective consideration", "Other".
- available_options: the holders' consideration choices, each in a few words separated by " | ", or "No holder election".
- default_option: what a holder receives without a valid election, in a few words.
- closing_conditions: the conditions to closing, each in a few words, separated by " | ".
- cash_consideration_qualifications: terms that change or condition the cash amount, separated by " | ".
- stock_exchange_ratio_qualifications: collars, caps, adjustments or fractional-share treatment of the ratio, separated by " | ".
- other_consideration: consideration that is neither cash nor stock (e.g. contingent value rights), briefly.
- event_status_details: a short note supporting the status (agreement date, approvals obtained, what was amended).

Excerpts:
"""


def excerpts(text: str, selector: Selector) -> str:
    """Learned windows plus the original keyword windows, in filing order, up to MAX_CHARS."""
    chosen = {o: c for o, c in selector.select(text, per_field=5, max_windows=50)}
    chosen.update({o: c for o, c in common.select_windows(text, max_windows=12)})
    parts, size = [], 0
    for _, chunk in sorted(chosen.items()):
        chunk = re.sub(r"\s+", " ", chunk).strip()
        if size + len(chunk) > MAX_CHARS:
            break
        parts.append(chunk)
        size += len(chunk)
    return "\n---\n".join(parts)


def _call(prompt: str, strict_json: bool, max_tokens: int) -> dict:
    payload = {"model": MODEL, "think": False, "stream": False,
               "options": {"temperature": 0, "num_ctx": 12288, "num_predict": max_tokens},
               "messages": [{"role": "user", "content": prompt}]}
    if strict_json:
        payload["format"] = "json"
    request = urllib.request.Request(URL, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(request, timeout=600) as response:
        return json.loads(response.read())


def ask(prompt: str) -> tuple[dict, dict]:
    """One answer per filing. Ollama returns HTTP 500 when a strict-JSON answer is cut off at the token limit, so the
    retries allow a longer answer, the last one without strict JSON mode (the JSON object is read from the text). If all
    fail, the filing gets no answer and the error is recorded, so a run never stops on one filing."""
    reply, errors = None, []
    for attempt, (strict, max_tokens) in enumerate(((True, 900), (True, 2000), (False, 2000))):
        try:
            reply = _call(prompt, strict, max_tokens)
            break
        except Exception as exc:  # noqa: BLE001  (Ollama occasionally returns HTTP 500 on one request)
            errors.append(f"attempt {attempt + 1}: {exc}")
            time.sleep(5)
    if reply is None:
        return {}, {"error": " | ".join(errors)}
    content = reply["message"]["content"]
    try:
        answer = json.loads(content)
    except json.JSONDecodeError:
        found = re.search(r"\{.*\}", content, re.S)
        try:
            answer = json.loads(found.group(0)) if found else {}
        except json.JSONDecodeError:
            answer = {}
    usage = {"prompt_tokens": reply.get("prompt_eval_count"), "output_tokens": reply.get("eval_count"),
             "seconds": round((reply.get("total_duration") or 0) / 1e9, 1)}
    if errors:
        usage["retried"] = " | ".join(errors)
    return (answer if isinstance(answer, dict) else {}), usage


EMPTY = re.compile(r"^(?:none|null|n/?a|not\s+(?:stated|specified|mentioned|applicable|provided|available)|unknown|"
                   r"no\s+information|-+)\.?$", re.I)


def clean(value) -> str:
    """Qwen's way of saying 'not stated' ("None", "N/A", "Not specified") counts as no answer."""
    if value is None:
        return ""
    if isinstance(value, list):
        value = " | ".join(str(v) for v in value)
    value = str(value).strip()
    return "" if EMPTY.match(value) else value


def predict_all(accs: list[str], forms: dict, filed: dict, fields: list[str]) -> dict:
    cache = {}
    if CACHE.exists():
        for line in CACHE.read_text().splitlines():
            row = json.loads(line)
            cache[row["accession_number"]] = row
    selector = Selector.load()
    out = {}
    with CACHE.open("a") as fh:
        for n, acc in enumerate(accs, 1):
            if acc not in cache:
                started = time.time()
                answer, usage = ask(PROMPT + excerpts(common.filing_text(acc), selector))
                cache[acc] = {"accession_number": acc, "answer": answer, **usage}
                fh.write(json.dumps(cache[acc]) + "\n")
                fh.flush()
                print(f"Qwen {n}/{len(accs)} {acc} {time.time() - started:.0f}s", flush=True)
            answer = cache[acc]["answer"]
            out[acc] = {f: (clean(answer.get(f)), "Qwen3 4B on selected excerpts") for f in fields}
    return out
