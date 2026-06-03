#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
生成站点组件参数表
===================
补充缺失的光伏组件参数，使用默认值填充。
"""
from pathlib import Path
import pandas as pd
import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "tables"
METRICS_DIR = PROJECT_ROOT / "output" / "pv_pipeline" / "metrics"
METRICS_DIR.mkdir(parents=True, exist_ok=True)

# 组件参数默认值
DEFAULT_PARAMS = {
    "rooftop": {
        "tilt_deg": 15,
        "azimuth_deg": 180,
        "module_gamma_pdc": -0.004,
        "loss_factor": 0.85,
        "inverter_efficiency": 0.98,
        "mount_type": "roof_mounted",
        "parameter_source": "rooftop_default",
    },
    "ground": {
        "tilt_deg": 25,
        "azimuth_deg": 180,
        "module_gamma_pdc": -0.004,
        "loss_factor": 0.85,
        "inverter_efficiency": 0.98,
        "mount_type": "ground_mounted",
        "parameter_source": "ground_default",
    },
    "default": {
        "tilt_deg": 20,
        "azimuth_deg": 180,
        "module_gamma_pdc": -0.004,
        "loss_factor": 0.85,
        "inverter_efficiency": 0.98,
        "mount_type": "unknown",
        "parameter_source": "unknown_default",
    },
}

# 电池板类型与温度系数映射
CELL_TYPE_GAMMA = {
    "单晶硅": -0.004,
    "多晶硅": -0.004,
    "薄膜": -0.002,
    "HIT": -0.0025,
    "PERC": -0.004,
    "unknown": -0.004,
}

# 安装类型与倾角映射
INSTALL_TYPE_TILT = {
    "屋顶": 15,
    "屋面": 15,
    "地面": 25,
    "山地": 20,
    "水面": 15,
    "BIPV": 10,
}


def get_install_type(install_type_raw):
    """根据原始安装类型推断安装类别"""
    if pd.isna(install_type_raw):
        return "default"
    install_type = str(install_type_raw).lower()
    if "屋顶" in install_type or "屋面" in install_type or "bipv" in install_type:
        return "rooftop"
    elif "地面" in install_type or "山地" in install_type or "水面" in install_type:
        return "ground"
    else:
        return "default"


def get_cell_type_gamma(cell_type):
    """获取电池板温度系数"""
    if pd.isna(cell_type):
        return CELL_TYPE_GAMMA["unknown"]
    for cell_key, gamma in CELL_TYPE_GAMMA.items():
        if cell_key in str(cell_type):
            return gamma
    return CELL_TYPE_GAMMA["unknown"]


def get_install_tilt(install_type_raw):
    """获取安装倾角"""
    if pd.isna(install_type_raw):
        return DEFAULT_PARAMS["default"]["tilt_deg"]
    for type_key, tilt in INSTALL_TYPE_TILT.items():
        if type_key in str(install_type_raw):
            return tilt
    return DEFAULT_PARAMS["default"]["tilt_deg"]


def generate_parameter_table(site_master_path):
    """生成站点组件参数表"""
    print("=" * 60)
    print("生成站点组件参数表")
    print("=" * 60)

    # 读取站点主表
    df = pd.read_csv(site_master_path)
    print(f"\n读取站点主表: {len(df)} 个站点")

    # 获取默认参数
    def get_params(row):
        install_type = get_install_type(row.get("install_type_raw", None))
        defaults = DEFAULT_PARAMS.get(install_type, DEFAULT_PARAMS["default"])

        tilt = get_install_tilt(row.get("install_type_raw", None))
        gamma = get_cell_type_gamma(row.get("cell_type", None))

        return pd.Series({
            "site_id": row["site_id"],
            "site_short_name": row.get("site_short_name", ""),
            "capacity_mw": row.get("capacity_mw", 0),
            "county": row.get("county", ""),
            "install_type_raw": row.get("install_type_raw", ""),
            "cell_type": row.get("cell_type", ""),
            "tilt_deg": tilt,
            "azimuth_deg": defaults["azimuth_deg"],
            "module_gamma_pdc": gamma,
            "loss_factor": defaults["loss_factor"],
            "inverter_efficiency": defaults["inverter_efficiency"],
            "mount_type": defaults["mount_type"],
            "parameter_source": defaults["parameter_source"],
        })

    param_df = df.apply(get_params, axis=1)

    # 统计参数来源
    source_counts = param_df["parameter_source"].value_counts()
    print("\n参数来源统计:")
    print(source_counts)

    # 保存
    output_path = METRICS_DIR / "site_parameter_completeness.csv"
    param_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"\n保存: {output_path}")

    # 生成参数完整性报告
    report_path = METRICS_DIR / "site_parameter_completeness.md"
    with open(report_path, "w") as f:
        f.write("# 站点参数完整性报告\n\n")
        f.write("## 1. 参数来源说明\n\n")
        f.write("| 来源类型 | 说明 | 站点数 |\n")
        f.write("|---------|------|--------|\n")
        for source, count in source_counts.items():
            f.write(f"| {source} | ")
            if "rooftop" in source:
                f.write("屋顶安装默认参数（倾角15°，方位180°）")
            elif "ground" in source:
                f.write("地面安装默认参数（倾角25°，方位180°）")
            elif "county" in source:
                f.write("县级统计平均参数")
            else:
                f.write("未知类型默认参数")
            f.write(f" | {count} |\n")

        f.write("\n## 2. 参数说明\n\n")
        f.write("- **tilt_deg**: 光伏板倾角（度）\n")
        f.write("- **azimuth_deg**: 光伏板方位角（度，180=正南）\n")
        f.write("- **module_gamma_pdc**: 功率温度系数（/°C）\n")
        f.write("- **loss_factor**: 系统损耗因子\n")
        f.write("- **inverter_efficiency**: 逆变器效率\n")
        f.write("- **mount_type**: 安装方式（屋顶/地面/其他）\n\n")

        f.write("## 3. 对模型误差的影响\n\n")
        f.write("### 早晚时段误差影响\n")
        f.write("倾角和方位角主要影响早晚低太阳高度角时的辐照度计算。\n")
        f.write("当前使用统一默认值，可能导致：\n")
        f.write("- 6点、19点误差偏大\n")
        f.write("- 不同朝向屋顶误差不一致\n\n")

        f.write("### 建议\n")
        f.write("1. 现场测量或从设计图纸获取精确倾角/方位角\n")
        f.write("2. 对误差较大的站点优先补录参数\n")
        f.write("3. 下一版本引入 pvlib 计算 POA 辐照度\n")

    print(f"保存: {report_path}")

    # 参数统计
    print("\n参数统计:")
    print(param_df.describe())

    print("\n" + "=" * 60)
    print("组件参数表生成完成")
    print("=" * 60)

    return param_df


def main():
    site_master_path = OUT_DIR / "site_master.csv"
    if not site_master_path.exists():
        print(f"[ERROR] 文件不存在: {site_master_path}")
        return

    generate_parameter_table(site_master_path)


if __name__ == "__main__":
    main()
