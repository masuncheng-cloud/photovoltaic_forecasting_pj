#!/usr/bin/env python3
"""
pipeline_cache.py
=================
流水线指纹缓存与增量执行工具。

功能：
  - 文件指纹（SHA256）
  - 步骤级缓存（输入指纹 + 输出文件列表）
  - 增量跳过：输入未变化且输出存在时跳过

用法：
    from scripts.pipeline_cache import PipelineCache, file_fingerprint

    cache = PipelineCache(cache_dir, force=False)
    if not cache.needs_run("stage01_clean", input_files):
        print("SKIP stage01_clean — cache hit")
    else:
        # ... do work ...
        cache.record_finished("stage01_clean", input_files, output_files)

始终执行的步骤（不允许跳过）：
    manifest 写出
    posttrain_validation
    dashboard freshness check

用法示例：
    python scripts/pipeline_cache.py --check stage06_distributed_model
    python scripts/pipeline_cache.py --clear stage06_distributed_model
    python scripts/pipeline_cache.py --stats
"""

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def file_fingerprint(path: str | Path) -> dict:
    """返回文件的指纹信息。"""
    p = Path(path)
    if not p.exists():
        return {"exists": False, "path": str(p)}
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return {
        "exists": True,
        "path": str(p),
        "size": p.stat().st_size,
        "mtime": p.stat().st_mtime,
        "sha256": h.hexdigest(),
    }


def fingerprint_set(paths: list[str | Path]) -> dict[str, dict]:
    """返回多个文件的指纹字典。"""
    return {str(p): file_fingerprint(p) for p in paths}


class PipelineCache:
    """流水线步骤级缓存。"""

    # 始终执行的步骤（不允许跳过）
    ALWAYS_RUN = {
        "manifest",
        "posttrain_validation",
        "dashboard_freshness",
        "dashboard_check",
    }

    def __init__(self, cache_dir: str | Path | None = None, force: bool = False):
        if cache_dir is None:
            cache_dir = project_root() / "output" / "pv_pipeline" / "cache"
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.force = force

    def _cache_path(self, step: str) -> Path:
        return self.cache_dir / f"{step}.json"

    def needs_run(self, step: str, input_files: list[str | Path] | None = None,
                  output_files: list[str | Path] | None = None) -> bool:
        """
        判断步骤是否需要运行。

        Returns True（需要运行）如果：
          - force=True
          - step 在 ALWAYS_RUN 中
          - 步骤缓存不存在
          - 输入指纹发生变化
          - 输出文件不存在

        Returns False（跳过）如果：
          - 缓存存在
          - 输入指纹未变化
          - 输出文件全部存在
        """
        if self.force or step in self.ALWAYS_RUN:
            return True

        cache_path = self._cache_path(step)
        if not cache_path.exists():
            return True

        try:
            prev = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            return True

        # 检查输入指纹
        if input_files:
            prev_inputs = prev.get("input_fingerprints", {})
            cur_inputs = fingerprint_set(input_files)
            for p, cur_fp in cur_inputs.items():
                prev_fp = prev_inputs.get(p, {})
                if cur_fp.get("sha256") != prev_fp.get("sha256"):
                    return True
                # 文件不存在但缓存认为存在，也需要重跑
                if not cur_fp.get("exists") and prev_fp.get("exists"):
                    return True

        # 检查输出文件是否都存在
        if output_files:
            for p in output_files:
                if not Path(p).exists():
                    return True

        return False

    def record_finished(self, step: str,
                        input_files: list[str | Path] | None = None,
                        output_files: list[str | Path] | None = None,
                        status: str = "PASS",
                        extra: dict | None = None) -> None:
        """记录步骤执行结果到缓存。"""
        cur_inputs = fingerprint_set(input_files or [])
        cur_outputs = []
        for p in (output_files or []):
            fp = file_fingerprint(p)
            if fp["exists"]:
                cur_outputs.append({
                    "path": str(p),
                    "sha256": fp["sha256"],
                    "size": fp["size"],
                    "mtime": fp["mtime"],
                })

        record = {
            "step": step,
            "finished_at": datetime.now().isoformat(timespec="seconds"),
            "status": status,
            "input_fingerprints": cur_inputs,
            "output_files": cur_outputs,
        }
        if extra:
            record.update(extra)

        cache_path = self._cache_path(step)
        cache_path.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")

    def clear(self, step: str | None = None) -> None:
        """清除缓存。step=None 时清除全部。"""
        if step:
            p = self._cache_path(step)
            if p.exists():
                p.unlink()
                print(f"[OK] 清除缓存: {p.name}")
        else:
            for p in self.cache_dir.glob("*.json"):
                p.unlink()
            print(f"[OK] 清除全部缓存: {self.cache_dir}")

    def stats(self) -> None:
        """打印缓存统计。"""
        files = sorted(self.cache_dir.glob("*.json"))
        if not files:
            print("缓存为空。")
            return
        print(f"\n缓存目录: {self.cache_dir}")
        print(f"缓存条目: {len(files)}\n")
        for p in files:
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
                inputs = d.get("input_fingerprints", {})
                outputs = d.get("output_files", [])
                status = d.get("status", "?")
                finished = d.get("finished_at", "?")
                print(f"  {p.stem:<40} {status:<6} {finished}  inputs={len(inputs)} outputs={len(outputs)}")
            except Exception as e:
                print(f"  {p.name}: ERROR {e}")


def main():
    parser = argparse.ArgumentParser(description="流水线缓存工具")
    parser.add_argument("--check", type=str, metavar="STEP",
                        help="检查步骤是否需要运行")
    parser.add_argument("--clear", type=str, metavar="STEP",
                        help="清除指定步骤缓存（省略则清除全部）")
    parser.add_argument("--stats", action="store_true",
                        help="显示缓存统计")
    parser.add_argument("--force", action="store_true",
                        help="强制重新运行（忽略缓存）")
    args = parser.parse_args()

    cache = PipelineCache(force=args.force)

    if args.clear is not None:
        cache.clear(args.clear)
    elif args.stats:
        cache.stats()
    elif args.check:
        needs = cache.needs_run(args.check)
        print(f"{'NEED RUN' if needs else 'CACHE HIT (skip)'} — {args.check}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
