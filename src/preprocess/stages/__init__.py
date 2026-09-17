"""Preprocess stages."""

from src.preprocess.stages.assemble import AssembleStage
from src.preprocess.stages.cleanup import CleanupStage
from src.preprocess.stages.download import DownloadStage
from src.preprocess.stages.gliner_ie import GlinerStage
from src.preprocess.stages.inventory import InventoryStage
from src.preprocess.stages.load_db import LoadDbStage
from src.preprocess.stages.segment import SegmentStage

STAGE_REGISTRY = {
    "inventory": InventoryStage,
    "download": DownloadStage,
    "cleanup": CleanupStage,
    "segment": SegmentStage,
    "gliner": GlinerStage,
    "assemble": AssembleStage,
    "load_db": LoadDbStage,
}

__all__ = ["STAGE_REGISTRY"]
