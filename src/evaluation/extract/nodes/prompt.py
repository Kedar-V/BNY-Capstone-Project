"""prompt: render the stage's extraction prompt from the evidence bundle."""

from __future__ import annotations

from typing import Any

from src.evaluation.action_packs.base import ActionPack
from src.evaluation.extract.prompts import select_prompt
from src.evaluation.extract.providers import CLAUSE_PREFIX
from src.evaluation.extract.state import ExtractState


def make_prompt(pack: ActionPack):
    def prompt(state: ExtractState) -> dict[str, Any]:
        stage = state.stage()
        assert state.bundle is not None
        text = state.bundle.text
        if stage.prompt_mode == "copy" and text.startswith(CLAUSE_PREFIX):
            text = text[len(CLAUSE_PREFIX) :]
        return {"prompt": select_prompt(pack, state.request.field, text, mode=stage.prompt_mode)}

    return prompt
