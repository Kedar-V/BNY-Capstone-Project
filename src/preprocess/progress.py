"""Shared tqdm progress helpers."""

from __future__ import annotations

import os
import sys
from typing import Iterable, Iterator, TypeVar

T = TypeVar("T")


def progress_enabled(show_progress: bool | None = None) -> bool:
    if os.environ.get("PREPROCESS_NO_PROGRESS", "").strip() in {"1", "true", "True", "yes"}:
        return False
    if show_progress is False:
        return False
    if show_progress is True:
        return True
    return sys.stderr.isatty()


class _PlainProgress(Iterator[T]):
    """Iterable wrapper with no-op set_postfix for non-tqdm runs."""

    def __init__(self, iterable: Iterable[T]) -> None:
        self._it = iter(iterable)

    def __iter__(self) -> Iterator[T]:
        return self

    def __next__(self) -> T:
        return next(self._it)

    def set_postfix(self, *args, **kwargs) -> None:  # noqa: ANN002, ANN003
        return None


def stage_progress(
    iterable: Iterable[T],
    *,
    desc: str,
    total: int | None = None,
    unit: str = "it",
    show: bool | None = None,
    **kwargs,
) -> Iterable[T]:
    """Return tqdm (or plain wrapper) so callers can use set_postfix."""
    enabled = progress_enabled(show)
    if not enabled:
        return _PlainProgress(iterable)
    from tqdm import tqdm

    return tqdm(
        iterable,
        desc=desc,
        total=total,
        unit=unit,
        file=sys.stderr,
        **kwargs,
    )
