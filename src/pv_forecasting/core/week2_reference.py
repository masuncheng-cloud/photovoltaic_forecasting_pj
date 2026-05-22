from __future__ import annotations


# 周二版基准指标（2026-05-19）
# 仅作为对比基准，不参与训练计算
WEEK2_REFERENCE = {
    "rows": 67102,
    "sites": 53,
    "actual_mwh": 83409.19,
    "pred_mwh": 79138.30,
    "pred_actual_ratio": 0.9488,
    "bias_pct": -5.12,
    "mae_mw": 0.4547,
    "rmse_mw": 0.9676,
}


# 周二版逐小时 NRMSE（容量归一化口径）
WEEK2_HOURLY_NRMSE = {
    6:  {"rows": 1143,  "site_nrmse_mean_pct": 5.66,  "city_nrmse_pct": 14.400},
    7:  {"rows": 4309,  "site_nrmse_mean_pct": 5.67,  "city_nrmse_pct": 5.904},
    8:  {"rows": 6174,  "site_nrmse_mean_pct": 7.09,  "city_nrmse_pct": 2.949},
    9:  {"rows": 6289,  "site_nrmse_mean_pct": 10.12, "city_nrmse_pct": 1.659},
    10: {"rows": 6326,  "site_nrmse_mean_pct": 11.63, "city_nrmse_pct": 2.763},
    11: {"rows": 6339,  "site_nrmse_mean_pct": 12.02, "city_nrmse_pct": 1.243},
    12: {"rows": 6352,  "site_nrmse_mean_pct": 12.48, "city_nrmse_pct": 0.142},
    13: {"rows": 6345,  "site_nrmse_mean_pct": 12.50, "city_nrmse_pct": 1.088},
    14: {"rows": 6334,  "site_nrmse_mean_pct": 11.55, "city_nrmse_pct": 0.989},
    15: {"rows": 6313,  "site_nrmse_mean_pct": 9.65,  "city_nrmse_pct": 1.569},
    16: {"rows": 6173,  "site_nrmse_mean_pct": 6.17,  "city_nrmse_pct": 2.269},
    17: {"rows": 3180,  "site_nrmse_mean_pct": 5.32,  "city_nrmse_pct": 5.906},
    18: {"rows": 1143,  "site_nrmse_mean_pct": 5.02,  "city_nrmse_pct": 12.663},
    19: {"rows": 682,   "site_nrmse_mean_pct": 15.01, "city_nrmse_pct": 19.180},
}
