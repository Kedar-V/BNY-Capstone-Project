"""Download a form set for a filing-date range with edgartools, then extract with GLiNER.

Example from the repository root:
    python dataloader/edgar_action_loader.py --action tender_offer --start 2024-01-01 --end 2024-01-31 --n 5
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
EVAL = ROOT / "notebooks" / "evaluation"
for _path in (ROOT, ROOT / "src", ROOT / "dataloader", EVAL):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))

from download_samples import diversify  # noqa: E402

ACTIONS = json.loads((EVAL / "corporate_actions.json").read_text())
from src.preprocess.backends import GlinerBackend  # noqa: E402
from src.preprocess.contracts import GLINER_LABELS_TO, GLINER_PASS2_LABELS  # noqa: E402
from src.preprocess.paths import get_path_config  # noqa: E402
from src.preprocess.span_rank import (  # noqa: E402
    dedupe_nms,
    enrich_spans_with_passages,
    only_label_like_for_family,
)

_XBRL = ("EX-101", "EX-104")
_ACTION_PATH = {
    "tender_offer": "tender",
    "exchange_offer": "exchange",
    "rights_issue": "rights",
    "merger": "merger",
    "conversion": "conversion",
}


def document_role(document_type: str, form: str) -> str | None:
    """Primary form document or a non-XBRL exhibit. Everything else is dropped."""
    dtype = (document_type or "").upper()
    if dtype.startswith(_XBRL):
        return None
    if dtype.startswith("EX-"):
        return "exhibit"
    if dtype.removesuffix("/A") == (form or "").upper().removesuffix("/A"):
        return "primary"
    return None


def cleaned_documents(filing, form: str) -> list[dict]:
    """EdgarTools download + text cleanup for the documents we keep."""
    docs = []
    for att in filing.attachments:
        dtype = str(getattr(att, "document_type", "") or "")
        role = document_role(dtype, form)
        if role is None:
            continue
        text = att.text()
        text = "" if text is None else str(text).strip()
        docs.append(
            {
                "filename": str(getattr(att, "document", "") or dtype),
                "document_type": dtype,
                "description": str(getattr(att, "description", "") or ""),
                "role": role,
                "text": text,
            }
        )
    return docs


def labels_for(action: str) -> list[str]:
    # ponytail: only tender has its own label list; other actions reuse it until they get one
    labels = get_path_config(_ACTION_PATH[action]).gliner_labels
    return labels or list(GLINER_LABELS_TO)


def extract_documents(backend, docs: list[dict], labels: list[str]) -> list[dict]:
    """GLiNER plus the existing ranker, one pass per cleaned document."""
    spans: list[dict] = []
    texts: dict[str, str] = {}
    for i, doc in enumerate(docs):
        text = doc.get("text") or ""
        if not text:
            continue
        sid = f"{i}:{doc.get('filename')}"
        texts[sid] = text
        raw = [
            {**sp, "segment_id": sid, "doc_role": doc.get("role"), "filename": doc.get("filename"), "pass": 1}
            for sp in backend.predict(text, labels)
        ]
        weak = any(only_label_like_for_family(raw, fam) for fam in ("price", "date", "org"))
        if weak:
            raw.extend(
                {**sp, "segment_id": sid, "doc_role": doc.get("role"), "filename": doc.get("filename"), "pass": 2}
                for sp in backend.predict(text, list(GLINER_PASS2_LABELS))
            )
        spans.extend(raw)
    return enrich_spans_with_passages(dedupe_nms(spans), texts)


def _join(docs: list[dict]) -> str:
    chunks = []
    for doc in docs:
        if not doc.get("text"):
            continue
        chunks.append(
            f"=== DOCUMENT {doc['filename']} | {doc['document_type']} | {doc['role']} ===\n{doc['text']}"
        )
    return "\n\n".join(chunks)


def filing_meta(filing) -> dict:
    """Index fields off an edgartools Filing. No document download."""
    accession = str(getattr(filing, "accession_no", None) or getattr(filing, "accession_number", "") or "")
    filed = getattr(filing, "filing_date", "") or ""
    filed = filed.isoformat() if hasattr(filed, "isoformat") else str(filed)
    cik = str(getattr(filing, "cik", "") or "")
    return {
        "accession": accession,
        "primary_cik": cik,
        "file_date": filed[:10],
        "form": str(getattr(filing, "form", "") or ""),
        "entity_name": str(getattr(filing, "company", "") or ""),
        "year": int(filed[:4]) if filed[:4].isdigit() else None,
        "entity_key": cik,
    }


class EdgarActionLoader:
    """List forms in a date range with edgartools, then download, clean, and extract."""

    def __init__(self, user_agent: str | None = None, *, filings_source=None, backend=None):
        self.user_agent = user_agent or os.getenv("SEC_USER_AGENT")
        self.filings_source = filings_source or self._get_filings
        self.backend = backend

    def _get_filings(self, forms, start, end):
        """Every filing of these forms with a filing date in [start, end]."""
        if not self.user_agent:
            raise ValueError("Set SEC_USER_AGENT to your project/name and contact email")
        from edgar import get_filings, set_identity

        set_identity(self.user_agent)
        window = f"{start}:{end}"
        found = []
        for form in sorted({f.removesuffix("/A") for f in forms}):
            found.extend(get_filings(form=form, filing_date=window))
        return found

    def _backend(self):
        if self.backend is None:
            self.backend = GlinerBackend()
        return self.backend

    def load(
        self,
        action: str,
        start: str,
        end: str,
        n: int | None = None,
        include_supporting: bool = True,
        include_conditional: bool = False,
        output_dir: Path | None = None,
        force: bool = False,
    ) -> pd.DataFrame:
        if action not in ACTIONS:
            raise ValueError(f"Choose an action from {list(ACTIONS)}")
        spec = ACTIONS[action]
        forms = spec["primary"] + (spec["supporting"] if include_supporting else []) + (
            spec["conditional"] if include_conditional else []
        )
        output = Path(output_dir or EVAL / "data" / f"{action}_{start}_{end}").resolve()
        output.mkdir(parents=True, exist_ok=True)
        by_acc = {}
        rows = []
        for filing in self.filings_source(forms, start, end):
            meta = filing_meta(filing)
            by_acc[meta["accession"]] = filing
            rows.append(meta)
        pool = pd.DataFrame(rows)
        if not pool.empty:
            pool = pool[pool["form"].isin(forms)].dropna(subset=["accession", "primary_cik", "file_date"]).copy()
            dates = pd.to_datetime(pool["file_date"], errors="coerce")
            pool = pool[dates.between(pd.Timestamp(start), pd.Timestamp(end))].copy()
            pool["year"] = pd.to_datetime(pool["file_date"]).dt.year
            pool["entity_key"] = pool["primary_cik"].astype(str)
            pool = pool.sort_values("file_date").drop_duplicates("accession", keep="first")
            if n is not None:
                pool = diversify(pool, n)
        pool.to_csv(output / "selected_filings.csv", index=False)

        labels = labels_for(action)
        backend = self._backend()
        results = []
        for row in pool.to_dict("records"):
            acc = str(row["accession"])
            form = str(row["form"])
            text_path = output / "input_text" / f"{acc}.txt"
            text_path.parent.mkdir(parents=True, exist_ok=True)
            errors: list[str] = []
            docs: list[dict] = []
            cached = text_path.exists() and text_path.stat().st_size > 0 and not force
            if cached:
                text = text_path.read_text()
                docs = [{"filename": acc, "document_type": form, "role": "primary", "text": text, "description": ""}]
            else:
                try:
                    docs = cleaned_documents(by_acc[acc], form)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"Could not download the filing: {exc}")
                if docs and not any(d["role"] == "primary" and d["text"] for d in docs):
                    errors.append("Main document not found")
                empty = [d["filename"] for d in docs if not d["text"]]
                if empty:
                    errors.append("No text extracted: " + ", ".join(empty))
                text = _join(docs)
                text_path.write_text(text)
            try:
                spans = extract_documents(backend, docs, labels) if text.strip() else []
                extraction = "ok" if text.strip() else "empty"
            except Exception as exc:  # noqa: BLE001
                spans = []
                extraction = "failed"
                errors.append(str(exc))
            span_path = output / "spans" / f"{acc}.json"
            span_path.parent.mkdir(parents=True, exist_ok=True)
            span_path.write_text(json.dumps({"accession": acc, "spans": spans}))
            text_bytes = text.encode("utf-8")
            results.append(
                {
                    "action": action,
                    "accession_number": acc,
                    "form": form,
                    "filing_date": str(row["file_date"]),
                    "registrant_cik": str(row["primary_cik"]).zfill(10),
                    "registrant_name": row.get("entity_name"),
                    "event_id": f"{action}_{acc}",
                    "text": text,
                    "input_text_path": str(text_path),
                    "spans_path": str(span_path),
                    "spans": spans,
                    "n_spans": len(spans),
                    "document_count": sum(1 for d in docs if d.get("text")),
                    "text_char_count": len(text),
                    "input_hash": hashlib.sha256(text_bytes).hexdigest(),
                    "extraction": extraction,
                    "status": "failed" if not text.strip() else "partial" if errors else "ok",
                    "error": " | ".join(errors),
                }
            )
            pd.DataFrame(results).to_json(output / "filings.jsonl", orient="records", lines=True, force_ascii=False)
        frame = pd.DataFrame(results)
        if frame.empty:
            frame = pd.DataFrame(columns=["action", "accession_number", "form", "filing_date", "text", "spans", "status"])
        frame.to_json(output / "filings.jsonl", orient="records", lines=True, force_ascii=False)
        frame.drop(columns=[c for c in ("text", "spans") if c in frame.columns]).to_csv(output / "filings.csv", index=False)
        (output / "run.json").write_text(
            json.dumps(
                {
                    "action": action,
                    "start": start,
                    "end": end,
                    "n": n,
                    "downloader": "edgartools",
                    "extractor": "gliner",
                    "selected_filings": len(frame),
                },
                indent=2,
            )
        )
        return frame


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--action", choices=list(ACTIONS), required=True)
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--n", type=int)
    parser.add_argument("--primary-only", action="store_true")
    parser.add_argument("--include-conditional", action="store_true")
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    EdgarActionLoader().load(
        args.action,
        args.start,
        args.end,
        args.n,
        not args.primary_only,
        args.include_conditional,
        args.output_dir,
        args.force,
    )
