from __future__ import annotations

import os
import sys
import time
from typing import Iterable, Iterator, Optional, TypeVar

T = TypeVar("T")


def _progress_enabled() -> bool:
    return os.getenv("PV_PROGRESS", "1") not in {"0", "false", "False"}


def _progress_mode() -> str:
    return os.getenv("PV_PROGRESS_MODE", "tqdm").lower().strip()


def progress_iter(
    iterable: Iterable[T],
    *,
    total: Optional[int] = None,
    desc: str = "",
    unit: str = "it",
    min_interval: float = 0.5,
    leave: bool = True,
) -> Iterator[T]:
    """
    Unified progress iterator.

    Priority:
    1. PV_PROGRESS=0 disables all progress output.
    2. PV_PROGRESS_MODE=tqdm (default) uses tqdm for live single-line progress bar.
    3. PV_PROGRESS_MODE=log emits compact progress lines to stderr.

    tqdm is strongly preferred: it renders correctly only when stdout is a real TTY
    or when PYTHONUNBUFFERED=1.  Subprocess wrappers (run_full_pipeline.py) must
    pass subprocess stdout through without a pipe when PV_PROGRESS_MODE=tqdm.
    """
    if not _progress_enabled():
        yield from iterable
        return

    mode = _progress_mode()
    if mode == "tqdm":
        try:
            from tqdm.auto import tqdm
            yield from tqdm(
                iterable,
                total=total,
                desc=desc,
                unit=unit,
                dynamic_ncols=True,
                mininterval=min_interval,
                leave=leave,
                file=sys.stdout,
            )
            return
        except Exception:
            mode = "log"

    if mode == "log":
        start = time.time()
        count = 0
        total_text = str(total) if total is not None else "?"
        for item in iterable:
            count += 1
            if count == 1 or count % 1000 == 0 or (total is not None and count >= total):
                elapsed = time.time() - start
                pct = ""
                if total:
                    pct = f" {count / total * 100:.1f}%"
                print(f"[{desc}] {count}/{total_text}{pct} elapsed={elapsed:.1f}s", flush=True)
            yield item
        return

    yield from iterable


def stage_log(message: str) -> None:
    """Simple stage marker that always prints without tqdm interference."""
    print(message, flush=True)
