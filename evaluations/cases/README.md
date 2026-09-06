# evaluations/cases — S04 金标验收集

S04 的目标产物：为文档问答建立**小语料 + 分组金标**。本目录只放数据与契约，
不放任何检索/模型代码（那是 S05 之后的事）。

## 文件清单

| 文件 | 内容 |
|---|---|
| `corpus_manifest.json`（上级目录 `evaluations/`） | 4 份官方 PDF 的来源/版本/哈希/页数清单，金标 span 通过 `source_id + sha256 + 页码` 绑到它 |
| `topic_inventory.md`（上级目录 `evaluations/`） | 主题 × 芯片 覆盖矩阵（PRESENT / NOT_FOUND / AMBIGUOUS），决定哪些主题可做可回答金标 |
| `gold_spans.jsonl` | 所有证据原文片段（span），每条一行 JSON。**没有 chunk_id**——S04 用哈希+页码+原文绑定，chunk 映射推迟到 S05/S07 |
| `dev.jsonl` / `holdout.jsonl` | 普通语义组案例（目标 50 组 × 4 种语言表达 = 200 条；30 组 dev / 20 组 holdout） |
| `boundary_dev.jsonl` / `boundary_holdout.jsonl` | 边界案例：无答案 / 歧义 / 错误型号 / 否定 / 绝对最大值混淆等（目标 10 组 × 4 = 40 条） |
| `annotation_guide.md` | 完整数据契约：字段、作者顺序、split 规则、质量优先级 |
| `dataset_manifest.json` | S04.13 才生成：validator 算出的计数 + 评审状态（`holdout_sealed=false` 直到用户审核批准） |
| `tests/test_s04_evaluation_dataset.py` | 确定性结构校验器（无网络/无模型/无 Chroma），全量测试套件的一部分 |

## 快速校验

```powershell
& '.\.venv\python.exe' -B -m pytest tests/test_s04_evaluation_dataset.py -q
```

## 两条硬规则

1. **语义组绝不跨 split**：同一语义组的 4 种问法必须全部在同一 split；
   首批 10 组永久属于 dev，绝不挪入 holdout（validator 用常量锁定）。
2. **human_reviewed 在用户明确审核前恒为 false**：validator 强制执行；
   用户批准后按测试文件里的说明更新门禁，并由人补评审记录。

## 状态

- 2026-09-06：目录与契约建立；语料 4 份（MP4570 / TPS54331 / TPS562201+TPS562208 / LT8610）。
- 评审状态：见 `dataset_manifest.json`（S04.13 起）。在用户审核前，
  状态恒为 **S04 TECHNICAL DATASET COMPLETE / HUMAN REVIEW PENDING / S04 NOT YET FULLY ACCEPTED / S05 NOT STARTED**。
