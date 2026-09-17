"""Segment stage: DOM TOC + FAQ chunks (no field IE)."""

from __future__ import annotations

from typing import Any

from bs4 import BeautifulSoup, NavigableString, Tag

from src.eda.documents import html_to_text
from src.preprocess.contracts import PRIORITY_HEADING_PATTERNS, StageContext, StageResult
from src.preprocess.paths import get_path_config, stub_manifest
from src.preprocess.progress import stage_progress
from src.preprocess.stages.cleanup import _event_ids, strip_sec_wrapper
from src.preprocess.store import ArtifactStore, utc_now_iso

_BOILERPLATE_HEADINGS = (
    "table of contents",
    "signatures",
    "signature",
    "exhibit index",
    "calculation of filing fee",
    "filing fee",
)


def _is_priority_heading(heading: str) -> bool:
    h = (heading or "").lower()
    return any(p in h for p in PRIORITY_HEADING_PATTERNS)


def _is_boilerplate_heading(heading: str) -> bool:
    h = (heading or "").lower()
    return any(b in h for b in _BOILERPLATE_HEADINGS)


def _anchor_nodes(soup: BeautifulSoup) -> list[tuple[str, Tag]]:
    found: list[tuple[str, Tag]] = []
    seen: set[str] = set()
    for a in soup.find_all("a"):
        name = a.get("name") or a.get("id")
        if not name:
            continue
        name = str(name).strip()
        if not name or name in seen:
            continue
        seen.add(name)
        found.append((name, a))
    return found


def _heading_near(node: Tag, fallback: str) -> str:
    bold = node.find(["b", "strong"])
    if bold:
        return bold.get_text(" ", strip=True)[:200] or fallback
    parent = node.parent
    if isinstance(parent, Tag):
        b2 = parent.find(["b", "strong"])
        if b2:
            return b2.get_text(" ", strip=True)[:200] or fallback
    return fallback


def _collect_until(start: Tag, end: Tag | None) -> str:
    """Collect text from start through siblings until end anchor."""
    parts: list[str] = []
    # include start's parent block text if small wrapper
    for el in start.next_elements:
        if end is not None and el is end:
            break
        if end is not None and isinstance(el, Tag) and el is end:
            break
        if isinstance(el, NavigableString):
            t = str(el).strip()
            if t:
                parts.append(t)
        if isinstance(el, Tag) and el.name in {"script", "style"}:
            continue
        # stop if we hit another named anchor
        if isinstance(el, Tag) and el.name == "a" and (el.get("name") or el.get("id")) and el is not start:
            if end is None or el is end:
                break
            # if this is a different section anchor, stop
            if el.get("name") or el.get("id"):
                # only stop when this is the end or we've left start's region into next known anchor
                if end is not None and el is end:
                    break
                # If end is set and we somehow passed it, break; else continue until end
                if end is None:
                    break
    return "\n".join(parts).strip()


def segment_toc(html: str, doc_role: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    anchors = _anchor_nodes(soup)
    if len(anchors) < 2:
        return []

    segments: list[dict[str, Any]] = []
    for i, (name, node) in enumerate(anchors):
        end = anchors[i + 1][1] if i + 1 < len(anchors) else None
        text = _collect_until(node, end)
        if len(text) < 40:
            continue
        heading = _heading_near(node, text.split("\n", 1)[0][:200])
        if _is_boilerplate_heading(heading):
            continue
        priority = _is_priority_heading(heading)
        segments.append(
            {
                "segment_id": f"{doc_role}:section:{name}",
                "doc_role": doc_role,
                "kind": "priority_section" if priority else "toc_section",
                "priority": priority,
                "heading": heading,
                "anchor": name,
                "text": text[:50000],
            }
        )
    return segments


def segment_faq(html: str, doc_role: str) -> list[dict[str, Any]]:
    soup = BeautifulSoup(html, "lxml")
    faqs: list[dict[str, Any]] = []
    idx = 0

    def _append_faq(question: str, answer: str) -> None:
        nonlocal idx
        answer = (answer or "").strip()
        question = (question or "").strip()
        if not question or not answer or len(answer) < 10:
            return
        faqs.append(
            {
                "segment_id": f"{doc_role}:faq:{idx}",
                "doc_role": doc_role,
                "kind": "faq",
                "priority": True,
                "question": question,
                "heading": question,
                "text": answer[:20000],
            }
        )
        idx += 1

    # 1) bold/strong questions
    for node in soup.find_all(["b", "strong"]):
        q = node.get_text(" ", strip=True)
        if not q.endswith("?"):
            continue
        block = node
        while block and getattr(block, "name", None) not in {"p", "div", "li", "td", "body", "html"}:
            block = block.parent
        cursor = block.next_sibling if block else node.next_sibling
        answer_parts: list[str] = []
        steps = 0
        while cursor is not None and steps < 12:
            steps += 1
            if isinstance(cursor, NavigableString):
                t = str(cursor).strip()
                if t:
                    answer_parts.append(t)
                cursor = cursor.next_sibling
                continue
            if not isinstance(cursor, Tag):
                break
            if cursor.name in {"script", "style"}:
                cursor = cursor.next_sibling
                continue
            bold = cursor.find(["b", "strong"])
            if bold:
                btxt = bold.get_text(" ", strip=True)
                if btxt.endswith("?") or btxt.lower().startswith("q:"):
                    break
            t = cursor.get_text(" ", strip=True)
            if t:
                answer_parts.append(t)
            cursor = cursor.next_sibling
        _append_faq(q, "\n".join(answer_parts))

    # 2) dt/dd pairs
    for dt in soup.find_all("dt"):
        q = dt.get_text(" ", strip=True)
        dd = dt.find_next_sibling("dd")
        if dd:
            _append_faq(q if q.endswith("?") else q + ("?" if "?" not in q else ""), dd.get_text(" ", strip=True))

    # 3) paragraphs starting with Q:
    for p in soup.find_all("p"):
        t = p.get_text(" ", strip=True)
        if not t.lower().startswith("q:"):
            continue
        q = t[2:].strip()
        nxt = p.find_next_sibling("p")
        ans = nxt.get_text(" ", strip=True) if nxt else ""
        if ans.lower().startswith("a:"):
            ans = ans[2:].strip()
        _append_faq(q if q.endswith("?") else q + "?", ans)

    return faqs


def segment_document(html: str, doc_role: str, clean_text: str) -> tuple[list[dict[str, Any]], str]:
    toc = segment_toc(html, doc_role) if doc_role == "otp" else []
    faq = segment_faq(html, doc_role) if doc_role == "otp" else []
    # Ensure at least one priority chunk if heading text appears in clean/html but TOC missed it
    if doc_role == "otp" and not any(s.get("priority") for s in toc):
        blob = (html or "") + "\n" + (clean_text or "")
        low = blob.lower()
        if any(p in low for p in PRIORITY_HEADING_PATTERNS):
            # carve a priority window from clean text
            src = clean_text or html_to_text(html)
            for pat in PRIORITY_HEADING_PATTERNS:
                i = src.lower().find(pat)
                if i >= 0:
                    chunk = src[i : i + 12000]
                    toc.insert(
                        0,
                        {
                            "segment_id": f"{doc_role}:priority:sts",
                            "doc_role": doc_role,
                            "kind": "priority_section",
                            "priority": True,
                            "heading": src[i : i + 40],
                            "text": chunk,
                        },
                    )
                    break
    if toc:
        return toc + faq, "toc"
    if faq:
        return faq, "faq"
    text = clean_text or html_to_text(html)
    return [
        {
            "segment_id": f"{doc_role}:full",
            "doc_role": doc_role,
            "kind": "full_doc",
            "priority": False,
            "heading": doc_role,
            "text": text[:80000],
        }
    ], "full_doc"


class SegmentStage:
    name = "segment"

    def run(self, ctx: StageContext) -> StageResult:
        cfg = get_path_config(ctx.path_name)
        store = ArtifactStore(ctx.path_name, ctx.preprocess_root)
        if not cfg.implemented:
            payload = stub_manifest(ctx.path_name)
            path = store.write_stage_manifest(self.name, payload)
            return StageResult(stage=self.name, status="stub_not_implemented", metrics=payload, artifact_paths=[str(path)])

        event_ids = _event_ids(store, ctx, stage=self.name)
        n_ok = n_fail = 0
        n_toc = n_faq = n_fallback = 0
        errors: list[str] = []

        pbar = stage_progress(
            event_ids, desc="segment", total=len(event_ids), unit="event", show=ctx.show_progress
        )
        for eid in pbar:
            try:
                inv_path = store.inventory_path(eid)
                if not inv_path.exists():
                    raise FileNotFoundError("missing inventory")
                inv = store.read_json(inv_path)
                all_segs: list[dict[str, Any]] = []
                modes: list[str] = []
                for doc in inv.get("docs") or []:
                    accession = doc.get("accession") or ""
                    filename = doc.get("filename") or ""
                    role = doc.get("role") or "unknown"
                    raw_path = store.raw_path(eid, accession, filename)
                    clean_path = store.clean_text_path(eid, accession, filename)
                    if not raw_path.exists() and not clean_path.exists():
                        continue
                    html = ""
                    if raw_path.exists():
                        html = strip_sec_wrapper(raw_path.read_text(encoding="utf-8", errors="replace"))
                    clean = clean_path.read_text(encoding="utf-8") if clean_path.exists() else ""
                    segs, mode = segment_document(html or clean, role, clean)
                    for s in segs:
                        s["accession"] = accession
                        s["filename"] = filename
                        s["hit_id"] = doc.get("hit_id")
                    all_segs.extend(segs)
                    modes.append(mode)
                    if mode == "toc":
                        n_toc += 1
                    elif mode == "faq":
                        n_faq += 1
                    else:
                        n_fallback += 1

                payload = {
                    "event_id": eid,
                    "written_at": utc_now_iso(),
                    "n_segments": len(all_segs),
                    "modes": modes,
                    "segments": all_segs,
                }
                if not all_segs:
                    raise ValueError("zero segments")
                store.write_json(store.segments_path(eid), payload)
                n_ok += 1
            except Exception as exc:  # noqa: BLE001
                n_fail += 1
                errors.append(f"{eid}: {exc}")
            if hasattr(pbar, "set_postfix"):
                pbar.set_postfix(ok=n_ok, fail=n_fail, refresh=False)

        metrics = {
            "n_events_segmented": n_ok,
            "n_otp_toc_docs": n_toc,
            "n_otp_faq_only_docs": n_faq,
            "n_fallback_full_doc": n_fallback,
            "n_failed": n_fail,
            "n_events_pending": len(event_ids),
        }
        man = store.write_stage_manifest(self.name, {"status": "ok", "metrics": metrics, "errors": errors[:30]})
        return StageResult(
            stage=self.name,
            status="ok",
            n_success=n_ok,
            n_failed=n_fail,
            metrics=metrics,
            errors=errors,
            artifact_paths=[str(man)],
        )
