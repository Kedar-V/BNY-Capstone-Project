"""Path plugins: tender (full) + stubs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PathConfig:
    name: str
    mvp_event_type: str
    implemented: bool
    gliner_labels: list[str]


def get_path_config(name: str) -> PathConfig:
    from src.preprocess.contracts import GLINER_LABELS_TO

    configs = {
        "tender": PathConfig(
            name="tender",
            mvp_event_type="tender_offer",
            implemented=True,
            gliner_labels=list(GLINER_LABELS_TO),
        ),
        "exchange": PathConfig(
            name="exchange",
            mvp_event_type="exchange_offer",
            implemented=False,
            gliner_labels=[],
        ),
        "rights": PathConfig(
            name="rights",
            mvp_event_type="rights_issue",
            implemented=False,
            gliner_labels=[],
        ),
        "merger": PathConfig(
            name="merger",
            mvp_event_type="merger",
            implemented=False,
            gliner_labels=[],
        ),
        "conversion": PathConfig(
            name="conversion",
            mvp_event_type="conversion",
            implemented=False,
            gliner_labels=[],
        ),
    }
    if name not in configs:
        raise KeyError(f"Unknown path: {name}")
    return configs[name]


def stub_manifest(path_name: str) -> dict[str, Any]:
    cfg = get_path_config(path_name)
    return {
        "path": path_name,
        "mvp_event_type": cfg.mvp_event_type,
        "preprocess_status": "stub_not_implemented",
        "implemented": False,
    }
