"""Worker / device helpers for preprocess + eval."""

from __future__ import annotations

import os
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Iterable, TypeVar

T = TypeVar("T")
R = TypeVar("R")


def default_workers(override: int | None = None) -> int:
    if override is not None and override > 0:
        return override
    env = os.environ.get("PREPROCESS_WORKERS", "").strip()
    if env.isdigit() and int(env) > 0:
        return int(env)
    return max(1, os.cpu_count() or 1)


def pick_torch_device(requested: str | None = None) -> str:
    """Return cuda | mps | cpu. Env: GLINER_DEVICE / PREPROCESS_DEVICE."""
    req = (
        requested
        or os.environ.get("GLINER_DEVICE")
        or os.environ.get("PREPROCESS_DEVICE")
        or "auto"
    ).strip().lower()
    if req and req != "auto":
        return req
    try:
        import torch

        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            return "mps"
    except Exception:  # noqa: BLE001
        pass
    return "cpu"


def configure_torch_threads(n: int | None = None) -> int:
    n = default_workers(n)
    os.environ.setdefault("OMP_NUM_THREADS", str(n))
    os.environ.setdefault("MKL_NUM_THREADS", str(n))
    try:
        import torch

        torch.set_num_threads(n)
        if hasattr(torch, "set_num_interop_threads"):
            torch.set_num_interop_threads(max(1, min(n, 4)))
    except Exception:  # noqa: BLE001
        pass
    return n


def map_parallel(
    items: Iterable[T],
    fn: Callable[[T], R],
    *,
    workers: int,
    desc: str,
    show_progress: bool = True,
    on_result: Callable[[R], None] | None = None,
    postfix: Callable[[], dict[str, Any]] | None = None,
) -> list[R]:
    """Thread-pool map with tqdm; completion order. `postfix` refreshes live metrics."""
    items_list = list(items)
    if not items_list:
        return []
    workers = max(1, min(int(workers), len(items_list)))

    from src.preprocess.progress import progress_enabled

    bar = None
    if progress_enabled(show_progress):
        from tqdm import tqdm

        bar = tqdm(total=len(items_list), desc=desc, unit="it", file=sys.stderr)

    def _tick(r: R) -> None:
        if on_result:
            on_result(r)
        if bar is not None:
            if postfix:
                bar.set_postfix(postfix(), refresh=False)
            bar.update(1)

    out: list[R] = []
    try:
        if workers == 1:
            for item in items_list:
                r = fn(item)
                out.append(r)
                _tick(r)
            return out

        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(fn, item) for item in items_list]
            for fut in as_completed(futs):
                r = fut.result()
                out.append(r)
                _tick(r)
        return out
    finally:
        if bar is not None:
            bar.close()
