"""OTP segmentation must keep explicit min-tender absence windows."""

from __future__ import annotations

from src.preprocess.stages.segment import _ensure_condition_windows, segment_document


def test_ensure_condition_windows_injects_missing_absence():
    clean = (
        "SUMMARY. Other stuff. "
        "THE OFFER IS NOT CONDITIONED ON ANY MINIMUM NUMBER OR AMOUNTOF SHARES BEING TENDERED. "
        "THE OFFER IS, HOWEVER, SUBJECT TO OTHER CONDITIONS."
    )
    segs = [
        {
            "segment_id": "otp:faq:0",
            "doc_role": "otp",
            "kind": "faq",
            "priority": False,
            "heading": "What is the offer price?",
            "text": "The purchase price is NAV.",
        }
    ]
    out = _ensure_condition_windows(segs, clean_text=clean, doc_role="otp")
    assert len(out) > len(segs)
    blob = "\n".join(s["text"] for s in out).lower()
    assert "not conditioned on any minimum" in blob


def test_faq_only_otp_keeps_absence_via_segment_document():
    html = "<html><body><p>Q: Price?</p><p>A: NAV.</p></body></html>"
    clean = (
        "THE OFFER IS NOT CONDITIONED ON ANY MINIMUM NUMBER OF SHARES BEING TENDERED. "
        "Other conditions apply."
    )
    segs, mode = segment_document(html, "otp", clean)
    assert mode in {"faq", "toc", "full_doc"}
    blob = "\n".join(s.get("text") or "" for s in segs).lower()
    assert "not conditioned on any minimum" in blob
