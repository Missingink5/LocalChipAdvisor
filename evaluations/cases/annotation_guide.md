# S04 标注指南（Annotation Guide）

本文件是金标数据的唯一契约。validator（`tests/test_s04_evaluation_dataset.py`）
按本契约做确定性结构校验；语义正确性由人工评审把关（S04.12）。

## 0. 作者顺序：证据优先

每条可回答案例都必须先有原文，再有问题：

1. 从官方 PDF 中挑一个**真实知识点**（数字/条件/机制，带页码）；
2. 把对应的**原文短句**原样抄成 gold span（verbatim_text 必须与 PDF 提取文本逐字一致）；
3. 判断该知识点**能推出什么、不能推出什么**（required_qualifiers / forbidden_claims 由此而来）；
4. 最后才写 4 种语言表达的**等价问题**。

主题状态（`topic_inventory.md`）只有 `PRESENT` 才能产生 ANSWERED 金标；
`NOT_FOUND` 只能产生 INSUFFICIENT_EVIDENCE 案例，**不能**写成"该芯片没有此功能"。
`AMBIGUOUS` 同样只能产生证据不足案例。

## 1. Case 记录（dev.jsonl / holdout.jsonl / boundary_*.jsonl，每行一条）

| 字段 | 类型 | 约束 |
|---|---|---|
| `case_id` | str | 全局唯一；约定 `<semantic_group_id>.<lang>` |
| `semantic_group_id` | str | 同一语义组共享；组内语义等价、证据等价。**组绝不跨 split** |
| `split` | str | `dev` / `holdout`，必须与所在文件名一致 |
| `query` | str | 用户问题的自然语言表达（见 §4 四种语言组） |
| `language_group` | str | `zh_formal` / `zh_colloquial` / `en` / `zh_en_mixed`（普通组必须恰好 4 条全覆盖） |
| `session_context.explicit_product_ids` | [str] | 会话中已明确引用的型号；可为空 |
| `expected_intents` | [str] | 至少含 `document_qa` |
| `expected_status` | str | `ANSWERED` / `NEEDS_CLARIFICATION` / `INSUFFICIENT_EVIDENCE` / `OUT_OF_SCOPE` |
| `allowed_product_ids` | [str] | 金标答案允许涉及的型号集合（非空） |
| `gold_evidence_requirements` | [obj] | 见 §2，证据需求列表；ANSWERED 案例必须非空 |
| `required_qualifiers` | [str] | 答案**必须保留**的适用条件（例：["10°C 迟滞", "条件：VIN=12V"]） |
| `forbidden_claims` | [str] | 答案**禁止出现**的结论（例：["存在保护就保证任何工况不会损坏"]） |
| `human_reviewed` | bool | 用户明确审核前恒为 `false`（validator 门禁） |

`session_context` 里只有 `explicit_product_ids` 一个字段；其他会话上下文（"它"的指代、
前文修改等）属 S15 多轮场景，S04 不标注。

## 2. gold_evidence_requirements（证据需求）

每条案例可要求一个或多个互补知识点。评分语义（§7.1）：

- `{requirement_id, alternative_span_ids: [...]}`：**同一条 requirement 内**的 span 是
  互相替代的（命中任一即可，计一个知识点）；
- **多条 requirement 之间**是 AND：全部命中才算完整。

所以：

- 同一知识点在文档里有多处等价表述 → 放进同一条 requirement 的 alternative_span_ids；
- 答案需要两个互补知识点（如"阈值 + 迟滞"）→ 写成两条 requirement。

## 3. Gold span 记录（gold_spans.jsonl，每行一条）

| 字段 | 类型 | 约束 |
|---|---|---|
| `span_id` | str | 全局唯一；约定 `<语义组>.<n>` 或 `<主题>.<n>` |
| `source_id` | str | 必须在 `corpus_manifest.json` 中 |
| `product_ids` | [str] | 该 span 实际讨论的型号（必须 ⊆ 其文档覆盖的型号） |
| `source_sha256` | str | 必须等于 manifest 中该 source_id 的 sha256（大小写一致） |
| `pdf_page_start` / `pdf_page_end` | int | 1-based PDF 页，`start ≤ end`，且在文档页数内 |
| `section` | str | 原文所在章节标题（如 "Thermal Shutdown Protection"），便于人工复核 |
| `verbatim_text` | str | 与 PDF 提取文本**逐字一致**的短摘录（≤400 字符，无首尾空白） |
| `required_qualifiers` | [str] | 该 span 自身的适用条件（可为空，条件应在 case 层补全） |
| `human_reviewed` | bool | 同 case 规则 |

**S04 禁止 `chunk_id` 字段**：金标绑定 = SHA256 + 页码 + 原文。分块一变金标全失效
的问题留到 S05/S07 用 `gold_span_id → chunk_id 集合` 映射解决。

**verbatim 选句规则**：

- 必须选文本提取**干净**的行（TI PDF 的 °C/± 会变 mojibake，避开那些词所在行）；
- 曲线页（MP4570 P9-13 等）是图片，不能做 span；
- 双芯片文档（TPS562201/208）的 span 必须含具体型号名，不能拿 TPS562208 的句
  回答 TPS562201 的问题；
- **提取伪影规范化**：行尾空格与软连字符 U+00AD（断行处 `pre\xad vent`）是提取
  伪影，作者时统一去除；换行拼接一律用单空格。除此之外 verbatim 必须逐字一致
  （含原文笔误，如 MP4570 "it will turns on"）。

## 4. 四种语言表达

同一语义组的 4 条 query 必须**语义等价、同证据**，只变表达方式：

| language_group | 示例形态 |
|---|---|
| `zh_formal` | "MP4570 的过温保护阈值是多少？" |
| `zh_colloquial` | "这芯片太热了会自己停吗？" |
| `en` | "At what junction temperature does the MP4570 shut down?" |
| `zh_en_mixed` | "MP4570 的 thermal shutdown 温度点在哪？" |

组内 4 条只允许表达差异；谁要求的条件更多、谁多引一个知识点，就不是同一组。

## 5. Split 规则（防泄漏硬规则）

1. 语义组是 split 的原子单位：4 条表达同 split。
2. 首批 10 个语义组**永久 dev**，绝不挪入 holdout（validator 常量锁定组 ID）。
3. 目标配比：普通组 30 dev / 20 holdout；边界组也按共享语义拆组、不跨 split。
4. `holdout_sealed` 仅用户审核批准后才可为 true；S09-S11 只读 dev。

## 6. 边界案例的意图（§7.4 反例）

边界案例按共享语义分组（如"绝对最大值 vs 正常工作值"是一个组），每类至少覆盖：

- 口语歧义、省略条件、单位纠正、浪涌未知、结温混淆、额定类别混淆（ABS MAX vs 工作值）、
  型号混淆（同类文档功能 → 目标型号无证据）、否定请求、无答案（资料库不含）、
  未审核参数（文档可查 ≠ 自动 formal）。

`expected_status` 对应：澄清 → `NEEDS_CLARIFICATION`；资料没有 → `INSUFFICIENT_EVIDENCE`；
问非本语料范围 → `OUT_OF_SCOPE`（如"给我推荐一款芯片"属选型链，S04 不评）。

## 7. 质量优先级

**证据真实性 > 条件完整性 > 语义组等价性 > split 正确 > 数量**。

不为了凑 50×4+40 编造金标。数量不足时如实报告实际数字；
错误金标先修标注，不先调检索迎合错误答案。

## 8. 评审门（S04.12）

- `agent_checked=true`：作者（agent）已完成自检，可在记录里写明自检范围；
- `human_reviewed`：**只能由用户审核后置 true**。不得虚构 reviewer 名字/时间/依据/批准。
- 用户批准前，最终状态必须写：
  `S04 TECHNICAL DATASET COMPLETE / HUMAN REVIEW PENDING / S04 NOT YET FULLY ACCEPTED / S05 NOT STARTED`
- 2026-09-07 项目所有者完成前三批逐批批准，并明确预授权后续批次按同一
  复核、返修、验证方式执行；最终批次与文档依据记录在 `human_review.json`。
