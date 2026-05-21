from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .config import PipelinePaths
from .utils import ensure_dirs


def bootstrap_project_root(file_path: str, levels: int = 3):
    root = Path(file_path).resolve()
    for _ in range(levels):
        root = root.parent
    src = root / "src"
    if str(src) not in sys.path:
        sys.path.insert(0, str(src))
    return root


def build_parser(desc: str) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=desc)
    parser.add_argument("--data-root", type=str, default="data")
    parser.add_argument("--output-root", type=str, default="output/pv_pipeline")
    return parser


def make_paths(project_root: Path, args) -> PipelinePaths:
    data_root = (project_root / args.data_root).resolve()
    output_root = (project_root / args.output_root).resolve()
    paths = PipelinePaths(project_root=project_root, data_root=data_root, output_root=output_root)
    ensure_dirs(paths.output_root, paths.tables, paths.models, paths.metrics, paths.figures, paths.logs)
    return paths
