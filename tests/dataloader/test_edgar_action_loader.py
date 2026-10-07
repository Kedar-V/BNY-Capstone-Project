"""EdgarActionLoader keeps exhibits, drops XBRL, and ranks GLiNER spans."""

from __future__ import annotations

from dataloader.edgar_action_loader import EdgarActionLoader, document_role
from src.preprocess.backends import FakeSpanBackend


class _Att:
    def __init__(self, document_type, filename, text):
        self.document_type = document_type
        self.document = filename
        self.description = ""
        self._text = text

    def text(self):
        return self._text


class _Filing:
    def __init__(self, attachments):
        self.attachments = attachments
        self.form = "SC TO-T"
        self.accession_no = "0001-22-000001"
        self.filing_date = "2024-06-01"
        self.cik = 123
        self.company = "Dermira, Inc."


def test_document_role_skips_xbrl_and_keeps_exhibits():
    assert document_role("SC TO-T/A", "SC TO-T") == "primary"
    assert document_role("EX-99.A1", "SC TO-T") == "exhibit"
    assert document_role("EX-101.INS", "SC TO-T") is None
    assert document_role("EX-104", "SC TO-T") is None
    assert document_role("GRAPHIC", "SC TO-T") is None


def test_load_cleans_with_edgartools_then_extracts(tmp_path):
    filing = _Filing(
        [
            _Att("SC TO-T", "offer.htm", "Offeror Eli Lilly and Company target Dermira, Inc. Offer Price $18.75"),
            _Att("EX-99.A", "ex.htm", "The Offer expires on February 19, 2020."),
            _Att("EX-101.INS", "xbrl.xml", "do not keep this xbrl"),
            _Att("GRAPHIC", "logo.jpg", "not a document"),
        ]
    )
    seen = {}

    def filings_source(forms, start, end):
        seen["forms"] = list(forms)
        seen["window"] = (start, end)
        return [filing]

    backend = FakeSpanBackend(
        {
            "$18.75": [{"label": "offer_price_amount", "text": "$18.75", "score": 0.91}],
            "February 19, 2020": [{"label": "expiration_datetime", "text": "February 19, 2020", "score": 0.88}],
            "Dermira, Inc.": [{"label": "target_organization", "text": "Dermira, Inc.", "score": 0.84}],
            "Eli Lilly": [{"label": "offeror_organization", "text": "Eli Lilly and Company", "score": 0.86}],
        }
    )
    frame = EdgarActionLoader(filings_source=filings_source, backend=backend).load(
        "tender_offer", "2024-01-01", "2024-12-31", output_dir=tmp_path
    )

    assert seen["window"] == ("2024-01-01", "2024-12-31")
    assert "SC TO-T" in seen["forms"]
    assert "SC 14D9" in seen["forms"]
    assert list(frame["status"]) == ["ok"]
    assert "do not keep this xbrl" not in frame.loc[0, "text"]
    assert "logo.jpg" not in frame.loc[0, "text"]
    assert frame.loc[0, "document_count"] == 2
    labels = {sp["label"] for sp in frame.loc[0, "spans"]}
    assert {"offer_price_amount", "expiration_datetime", "target_organization", "offeror_organization"} <= labels
    assert (tmp_path / "spans" / "0001-22-000001.json").exists()
