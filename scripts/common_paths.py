"""
common_paths.py
===============
统一路径与配置加载工具。

所有正式脚本都应从 common_paths 导入路径，
禁止在脚本中直接硬编码 `output/pv_pipeline` 等路径。

用法：
    from scripts.common_paths import project_root, load_config, output_dir, dashboard_dir

    cfg = load_config()
    out = output_dir(cfg)
    print(out / "tables")
"""

from pathlib import Path
from typing import Optional
import yaml


def project_root() -> Path:
    """项目根目录（scripts/ 的上一级）。"""
    return Path(__file__).resolve().parents[1]


def config_path() -> Path:
    """默认配置文件路径。"""
    return project_root() / "configs" / "pipeline.yaml"


def load_config(config_path: Optional[str] = None) -> dict:
    """
    加载流水线配置。

    Args:
        config_path: 可选，指定配置文件路径。
                     默认为 configs/pipeline.yaml。

    Returns:
        配置字典。

    Raises:
        FileNotFoundError: 配置文件不存在。
        yaml.YAMLError: YAML 解析失败。
    """
    path = Path(config_path) if config_path else config_path()
    if not path.exists():
        raise FileNotFoundError(f"pipeline config not found: {path}")
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    _validate_config(cfg)
    return cfg


def _validate_config(cfg: dict) -> None:
    """基础配置校验。"""
    required = ["data", "split", "eval", "prediction", "dashboard"]
    for key in required:
        if key not in cfg:
            raise ValueError(f"pipeline config missing required top-level key: {key}")


def data_root(cfg: dict) -> Path:
    """原始数据目录。"""
    pr = project_root()
    root = cfg.get("data", {}).get("data_root", "data")
    return pr / root


def output_root(cfg: dict) -> Path:
    """训练输出根目录（output/pv_pipeline）。"""
    pr = project_root()
    root = cfg.get("data", {}).get("output_root", "output/pv_pipeline")
    return pr / root


def dashboard_dir(cfg: dict) -> Path:
    """可视化 dashboard 数据目录。"""
    pr = project_root()
    ddir = cfg.get("dashboard", {}).get("output_dir", "output/pv_pipeline/interactive_dashboard")
    return pr / ddir


def archive_root(cfg: dict) -> Path:
    """归档目录。"""
    pr = project_root()
    adir = cfg.get("archive", {}).get("archive_root", "archive")
    return pr / adir


def eval_hours(cfg: dict) -> tuple[int, int]:
    """评估小时范围 (start_hour, end_hour)。"""
    ev = cfg.get("eval", {})
    return int(ev.get("start_hour", 6)), int(ev.get("end_hour", 19))


def final_prediction_column(cfg: dict) -> str:
    """最终预测列名。"""
    return cfg.get("prediction", {}).get("final_column", "power_pred_final")


def split_dates(cfg: dict) -> dict:
    """返回 split 日期边界字典。"""
    sp = cfg.get("split", {})
    return {
        "train_start": sp.get("train_start", "2023-01-01"),
        "train_end":   sp.get("train_end",   "2025-06-30"),
        "valid_start": sp.get("valid_start", "2025-07-01"),
        "valid_end":   sp.get("valid_end",   "2025-08-31"),
        "test_start":  sp.get("test_start",  "2025-09-01"),
        "test_end":    sp.get("test_end",    "2025-12-31"),
    }
