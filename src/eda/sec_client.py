"""Thin SEC EDGAR / EFTS HTTP client."""

from __future__ import annotations

import gzip
import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Iterable

from .config import SEC_REQUEST_PAUSE_SEC, SEC_USER_AGENT


class SecClient:
    def __init__(
        self,
        user_agent: str = SEC_USER_AGENT,
        pause_sec: float = SEC_REQUEST_PAUSE_SEC,
    ) -> None:
        self.user_agent = user_agent
        self.pause_sec = pause_sec
        self._last_request = 0.0

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self.pause_sec:
            time.sleep(self.pause_sec - elapsed)

    def get_bytes(
        self,
        url: str,
        accept: str = "*/*",
        timeout: int = 90,
        retries: int = 5,
    ) -> bytes:
        last_err: Exception | None = None
        for attempt in range(retries + 1):
            self._throttle()
            req = urllib.request.Request(
                url,
                headers={
                    "User-Agent": self.user_agent,
                    "Accept": accept,
                    "Accept-Encoding": "gzip, deflate",
                },
            )
            try:
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    data = resp.read()
                    encoding = (resp.headers.get("Content-Encoding") or "").lower()
                    if encoding == "gzip" or data[:2] == b"\x1f\x8b":
                        data = gzip.decompress(data)
                    self._last_request = time.time()
                    return data
            except urllib.error.HTTPError as exc:
                self._last_request = time.time()
                last_err = RuntimeError(f"HTTP {exc.code} for {url}")
                # Retry transient SEC/EFTS failures.
                if exc.code not in {429, 500, 502, 503, 504} or attempt >= retries:
                    raise last_err from exc
                time.sleep(min(2 ** attempt, 20) + 0.25 * attempt)
            except (urllib.error.URLError, TimeoutError) as exc:
                self._last_request = time.time()
                last_err = exc
                if attempt >= retries:
                    raise RuntimeError(f"Request failed for {url}") from exc
                time.sleep(min(2 ** attempt, 20) + 0.25 * attempt)
        raise RuntimeError(f"Request failed for {url}") from last_err

    def get_json(self, url: str) -> Any:
        return json.loads(self.get_bytes(url, accept="application/json"))

    def get_text(self, url: str) -> str:
        raw = self.get_bytes(url, accept="text/html,application/xhtml+xml,text/plain,*/*")
        for enc in ("utf-8", "latin-1"):
            try:
                return raw.decode(enc)
            except UnicodeDecodeError:
                continue
        return raw.decode("utf-8", errors="replace")

    def efts_search(self, params: dict[str, Any]) -> dict[str, Any]:
        query = urllib.parse.urlencode(params, doseq=True)
        url = f"https://efts.sec.gov/LATEST/search-index?{query}"
        return self.get_json(url)

    def efts_paginate(
        self,
        *,
        q: str,
        forms: str,
        start: str,
        end: str,
        page_size: int = 100,
        max_records: int | None = None,
    ) -> list[dict[str, Any]]:
        """Fetch all EFTS hits for a date window. Caller must keep windows under ES 10k."""
        hits: list[dict[str, Any]] = []
        offset = 0
        total = None
        while True:
            payload = self.efts_search(
                {
                    "q": q,
                    "dateRange": "custom",
                    "startdt": start,
                    "enddt": end,
                    "forms": forms,
                    "from": offset,
                    "size": page_size,
                }
            )
            batch = payload.get("hits", {}).get("hits", [])
            if total is None:
                total_obj = payload.get("hits", {}).get("total", 0)
                total = total_obj["value"] if isinstance(total_obj, dict) else int(total_obj)
            hits.extend(batch)
            offset += len(batch)
            if not batch or offset >= total:
                break
            if max_records is not None and offset >= max_records:
                break
        return hits

    def filing_index(self, cik: str, accession: str) -> dict[str, Any]:
        cik_int = str(int(cik))
        acc_nodash = accession.replace("-", "")
        url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/index.json"
        return self.get_json(url)

    def document_url(self, cik: str, accession: str, filename: str) -> str:
        cik_int = str(int(cik))
        acc_nodash = accession.replace("-", "")
        return f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{acc_nodash}/{filename}"

    def iter_month_windows(self, start: str, end: str) -> Iterable[tuple[str, str]]:
        """Yield inclusive YYYY-MM-DD month windows clipped to [start, end]."""
        import datetime as dt

        start_d = dt.date.fromisoformat(start)
        end_d = dt.date.fromisoformat(end)
        cur = start_d.replace(day=1)
        while cur <= end_d:
            if cur.month == 12:
                nxt = cur.replace(year=cur.year + 1, month=1)
            else:
                nxt = cur.replace(month=cur.month + 1)
            win_start = max(cur, start_d)
            win_end = min(nxt - dt.timedelta(days=1), end_d)
            yield win_start.isoformat(), win_end.isoformat()
            cur = nxt
