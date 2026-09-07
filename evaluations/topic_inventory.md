# S04 主题清单（Topic Inventory）

状态：agent_checked=true；human_reviewed=true（2026-09-07 完成主题、案例、span 与文档级审核）。

本清单只回答一个问题：**某个主题在某份官方 PDF 里有没有真实、可定位的文字证据**。
每个主题标为 `PRESENT`（有明确文字，可做可回答金标）/ `NOT_FOUND`（关键词扫描无任何命中，不可做可回答金标）/ `AMBIGUOUS`（有标题或部分迹象，但不足以支撑"可回答"金标）。
`NOT_FOUND` 不得被改写成"该芯片没有此功能"的金标——只能做 INSUFFICIENT_EVIDENCE 案例。
页码均为 PDF 1-based 页码，来源为 PyMuPDF 逐页提取（有 page marker 的文本转储）。

## 一、主题 × 芯片 覆盖矩阵

| 主题 (theme) | MP4570 | TPS54331 | TPS562201/208 | LT8610 |
|---|---|---|---|---|
| input_range | PRESENT (P1,P5,P14) | PRESENT (P1,P4,P13-14) | PRESENT (P1,P9,P12) | PRESENT (P1,P12) |
| output_range | PRESENT (P4: 1V to 0.9·VIN，推荐工作条件行) | NOT_FOUND（P15 仅 set-point 章节） | PRESENT (P1: 0.76V-7V) | NOT_FOUND（FB 分压设定，无数值范围行） |
| output_current | PRESENT (P1: 3A) | PRESENT (P1,P9: 3A) | PRESENT (P9,P12: 2A) | PRESENT (P1,P13-15: 2.5A) |
| switching_frequency | PRESENT (P14,P17) | PRESENT (P9-10,P12: 固定 570kHz) | PRESENT (P9-11: ~580kHz 准固定) | PRESENT (P8,P12) |
| frequency_sync | PRESENT (P14: 100k-1MHz) | NOT_FOUND（固定振荡器，无同步） | NOT_FOUND（无同步引脚） | PRESENT (P10-11,P16) |
| soft_start | PRESENT (P15: 内部 0.5ms+外部可选) | PRESENT (P10-11: slow start, 无内部) | PRESENT (P9-10: 固定 1.0ms+prebias) | PRESENT (P15: 2.2µA, 0.97V) |
| enable_uvlo | PRESENT (P15-16: UVLO 3.9V, EN zener) | PRESENT (P3,P10-11: EN 1.25V+3µA) | PRESENT (P5,P10) | PRESENT (P1,P15-16: 1V+40mV) |
| ocp_current_limit | PRESENT (P15-16) | PRESENT (P9,P12,P14) | PRESENT (P10: valley detect) | PRESENT (P13-14) |
| short_circuit_protection | PRESENT（P15: 短路时 SS 放电、解除后重新软启动；P16: 低 FB 电流限值下降） | PRESENT (P9,P12: foldback ÷2/4/8) | PRESENT (P5,P10: UVP 256µs→hiccup 10ms) | PRESENT (P10,P13,P16: foldback) |
| overvoltage_protection | PRESENT (P15: OVP 115%/103%) | PRESENT (P13: OVTP 109%/107%, 瞬态) | AMBIGUOUS（P5 表头有 OVP 字样，无阈值/描述行） | NOT_FOUND |
| thermal_shutdown | PRESENT (P4,P16: 170/160°C) | PRESENT (P13: 165°C) | PRESENT (P5,P10: 160°C, non-latch) | PRESENT (P3,P16) |
| thermal_rating_ja | PRESENT (P4: θJA 45°C/W) | PRESENT (P5: RθJA) | PRESENT (P4: RθJA) | PRESENT (P2: θJA 40°C/W) |
| light_load_behavior | PRESENT (P14,P19: pulse skip 需 VIN−VOUT≥3V) | PRESENT (P9,P13: Eco-mode <160mA) | PRESENT (P9,P11: Eco-mode; TPS562208 FCCM) | PRESENT (P10-11,P16: Burst Mode 1.7µA sleep) |
| output_accuracy | PRESENT (P5,P10,P14-17) | PRESENT (P10: VREF 0.8V ±2%/±3.5%) | PRESENT (P1,P5,P13) | PRESENT (P2-5,P15-16) |
| power_good | PRESENT (P16) | NOT_FOUND（无 PG 输出） | NOT_FOUND（无 PG 输出） | PRESENT (P9-10,P16: ±9%) |
| quiescent_current | PRESENT (P5) | PRESENT (P5,P9: 110µA/1µA) | PRESENT (P1,P5,P20: <20µA) | PRESENT (P1,P11: 2.5µA) |
| layout_guidelines | PRESENT (P19-20) | PRESENT (P25-26) | PRESENT (P17-18) | PRESENT (P17) |
| emi_notes | NOT_FOUND（无 EMI 章节） | PRESENT (P27) | NOT_FOUND（仅 layout 提及 radiated emissions） | PRESENT (P17) |
| bootstrap_operation | PRESENT (P16,P19: 需外接二极管条件 VOUT/VIN>65%) | PRESENT (P3,P10,P20: 0.1µF 必需) | PRESENT (P14: 电容选择) | NOT_FOUND（内部自举，无需用户器件） |
| control_topology | PRESENT (P1,P14: peak current mode) | PRESENT (P10,P12: peak-current, 92µA/V) | PRESENT (P9: D-CAP2 adaptive on-time) | PRESENT (P10,P12: constant freq peak-current) |

## 二、NOT_FOUND / AMBIGUOUS 的边界说明（防止错误金标）

1. **MP4570 short_circuit_protection = PRESENT**：P15 明确写明输出短路时 FB 拉低、SS 放电，解除短路后重新软启动；P16 说明低 FB 时峰值和谷值电流限值下降。可以回答资料明确描述的行为，但不能扩展成“保证不会损坏”或擅自命名为 hiccup。
2. **LT8610 output_range = NOT_FOUND**：没有数值输出范围行（输出由 FB 分压设定，FB 调节到 0.970V 但不是输出范围）。"LT8610 输出电压范围是多少"→ 证据不足；只能说输出由分压设定，不能编数值范围。**MP4570 output_range = PRESENT**：P4 Recommended Operating Conditions 有 "Output Voltage VOUT … 1V to 0.9·VIN" 行（逐行复核时发现关键词扫描漏报，已更正；最初标 NOT_FOUND 是扫描错误，不是文档缺失）。
3. **TPS562201 overvoltage_protection = AMBIGUOUS**：P5 参数表头 "OUTPUT UNDERVOLTAGE AND OVERVOLTAGE PROTECTION"，但该表只有 VUVP 与 hiccup 行，无 OVP 阈值或正文描述。→ INSUFFICIENT_EVIDENCE，不能说"有/无 OVP"。
4. **TPS54331 overvoltage_protection**：正文写的是 **OVTP = 过压瞬态保护**（109%/107%×VREF，恢复输出故障时的过冲），不是通用 OVP。金标必须保留"transient/瞬态"限定。
5. **TPS54331 soft_start**：TI 文档用 "slow start" 措辞；外部 SS 电容设定 1-10ms，CSS≤27nF，**无内部 slow-start**。金标用词要按原文。
6. **TPS54331 frequency_sync = NOT_FOUND**：固定 570kHz 振荡器，无 SYNC 引脚。
7. **TPS562201 frequency_sync = NOT_FOUND**：无同步引脚，D-CAP2 为自适应导通时间（~580kHz 准固定，VIN<7V 时 TON 扩展至最低约 200kHz）。
8. **TPS54331/TPS562201 power_good = NOT_FOUND**：均无 PG 引脚。
9. **LT8610 overvoltage_protection / bootstrap_operation = NOT_FOUND**：无输出过压保护措辞；内部自举无需用户外接元件。
10. **TPS562201 emi_notes = NOT_FOUND**：无专门 EMI 章节；只有 layout 指南第 4 条"SW 走线尽量短而宽以减小辐射发射"——该句属于 layout_guidelines 主题。

## 三、Ambiguity 备注（作者须知）

- **TPS562201/208 双芯片共用一份 datasheet**：任何针对某一具体型号的金标，其 gold span 必须明确写出该型号名（如 P9 "The TPS562201 is designed with Advanced Eco-mode..."）；不允许用 TPS562208 的 FCCM 句回答 TPS562201 的问题。
- **TI 文本提取的 mojibake**：°C→掳C、±→鈥 等（PDF 字体编码导致）。verbatim_text 必须选提取干净的行（本清单引用的都是干净行），validator 不做逐字回读 PDF 比对。
- **曲线/图形页为图片**：MP4570 P9-13（曲线页）、TI 效率曲线等无法文本提取。不能以曲线为 gold span；图形内容只能做 INSUFFICIENT_EVIDENCE 案例。
- **绝对最大值 ≠ 正常工作值**：MP4570 ABS MAX VIN=60V 与工作范围 4.5-55V 分开；LT8610 结温超 150°C 注释属于 OTP 保护注释，不是工作额定。

## 四、扫描方法（可复现性）

- 关键词扫描脚本：`D:\Cache\Temp\s04_theme_sweep.py`（读 `D:\Cache\Temp\*_fulltext.txt`，输出 `D:\Cache\Temp\s04_theme_sweep.txt`）。
- 每行命中均人工复核过上下文（上表引用的页码和数字都来自原文行，见转储文件）。
- 扫描不是判定标准：NOT_FOUND 只表示"这些关键词在该转储中无命中"，不排除 OCR 或图片内容——因此 NOT_FOUND 只能产生证据不足案例，不能产生"功能不存在"的断言。
