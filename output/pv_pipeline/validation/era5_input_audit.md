# ERA5 输入文件预检报告

生成时间: 2026-06-04 11:24:27

## 1. 文件结构检查

| 年份 | 文件 | 状态 | 说明 |
|------|------|------|------|
| 2023 | instant | PASS | t2m units=K, 8760h (expected 8760), lat=(34.0, 35.0), lon=(118.5, 120.0) |
| 2023 | accum | PASS | ssrd units=J m**-2, 8760h (expected 8760), lat=(34.0, 35.0), lon=(118.5, 120.0) |
| 2024 | instant | PASS | t2m units=K, 8784h (expected 8784), lat=(34.0, 35.0), lon=(118.5, 120.0) |
| 2024 | accum | PASS | ssrd units=J m**-2, 8784h (expected 8784), lat=(34.0, 35.0), lon=(118.5, 120.0) |
| 2025 | instant | PASS | t2m units=K, 8760h (expected 8760), lat=(34.0, 35.0), lon=(118.5, 120.0) |
| 2025 | accum | PASS | ssrd units=J m**-2, 8760h (expected 8760), lat=(34.0, 35.0), lon=(118.5, 120.0) |

## 2. 空间范围检查

| 站点 | 名称 | 纬度 | 经度 | 状态 | 说明 |
|------|------|------|------|------|------|
| S032 | S032 | 32.488611 | 119.767511 | WARN | 站点落在推荐 ERA5 范围外 (北=True, 南=False, 西=True, 东=True) 【经纬度疑似异常（不在连云港常规范围），需人工核对。】 |
| S114 | S114 | nan | nan | WARN | 站点落在推荐 ERA5 范围外 (北=False, 南=False, 西=False, 东=False) |
| S117 | S117 | nan | nan | WARN | 站点落在推荐 ERA5 范围外 (北=False, 南=False, 西=False, 东=False) |
| S118 | S118 | nan | nan | WARN | 站点落在推荐 ERA5 范围外 (北=False, 南=False, 西=False, 东=False) |

## 3. 推荐 ERA5 空间范围

- North: 35.75
- West:  118.0
- South: 33.5
- East:  120.5

## 4. 替换 ERA5 前的通过条件

1. 变量仍为 t2m 和 ssrd
2. instant/accum 文件结构不变
3. 时间逐小时完整（2023:8760h, 2024:8784h, 2025:8760h）
4. 空间范围覆盖连云港站点（不含 S032 异常座标）
