# S04 评审摘要（Human Review Gate Material）

日期：2026-09-06
状态：**agent_checked=true；human_reviewed=false（全部）；holdout_sealed=false**
最终状态表述：**S04 TECHNICAL DATASET COMPLETE / HUMAN REVIEW PENDING / S04 NOT YET FULLY ACCEPTED / S05 NOT STARTED**

本文件是人工评审门（S04.12）的材料。机器可检查的不变量已由
`tests/test_s04_evaluation_dataset.py` 强制执行（9 项断言全绿）；语义质量
由下面的 agent 自检清单 + 人工评审项覆盖。**任何 human_reviewed 都只能由
用户明确审核后置 true；在用户批准前，本数据集不得进入最终成绩。**

## 一、数据集规模（validator 实算，2026-09-06）

| 项 | 数量 |
|---|---|
| 语料文档（corpus_manifest.json） | 4 份官方 datasheet |
| 普通语义组 | 50 组（dev 30 / holdout 20） |
| 普通案例 | 200 条（每组 4 种语言表达） |
| 边界组 | 10 组（dev 7 / holdout 3） |
| 边界案例 | 40 条 |
| gold spans | 79 条 |
| 状态分布 | ANSWERED 208 / INSUFFICIENT_EVIDENCE 24 / NEEDS_CLARIFICATION 4 / OUT_OF_SCOPE 4 |

## 二、Agent 自检清单（已执行并记录）

1. **来源真实性**：4 份 PDF 均从官方链接下载，SHA-256 已重算核对；
   manifest 中 `local_file` 逐文件存在且哈希一致（validator 强制）。
2. **verbatim 逐字回查**：79/79 span 的 verbatim_text 在对应文档提取文本中
   找到（`D:\Cache\Temp\s04_verbatim_check.py`，空白归一 + 软连字符伪影剔除后
   逐字匹配）。含原文笔误逐字保留：MP4570 "it will turns on again"、
   "50%xRFF"、"25%xRFE"、"following close loop operation"。
3. **页码锚点**：每个 span 的 `pdf_page_start/end` 由提取转储的页标记
   （`===== PDF PAGE n =====`）定位后填写；validator 强制 1-based 且不超
   文档页数。
4. **主题清单复核**：关键词扫描 + 逐页人工复核。发现并更正一处扫描漏报
   （MP4570 output_range 实为 PRESENT，P4 推荐工作条件行 1V to 0.9·VIN）。
   NOT_FOUND/AMBIGUOUS 主题只产生证据不足案例，不产生"功能不存在"断言。
5. **split 隔离**：语义组不跨 split、不跨 normal/boundary；首批 10 组永久
   dev（validator 常量锁定组 ID）；同组 4 表达语言集合恰为
   {zh_formal, zh_colloquial, en, zh_en_mixed}。
6. **替代/互补语义**：alternatives 只用于同知识点多处表述（如 MP4570 输入
   范围 P1 两处）；跨知识点用多条 requirement（AND 语义），案例中
   requirement_id 唯一。
7. **评审标记**：全部 case/span/document 的 human_reviewed=false；
   未虚构 reviewer 名字/时间/依据/批准。

## 三、人工评审项（需要用户审核的内容）

按优先级排序（与指南一致：证据真实性 > 条件完整性 > 语义组等价性 > split > 数量）：

1. **证据适用性**：每个 ANSWERED 案例的 required_qualifiers 是否忠实于
   span 原文的条件（典型值/测试条件/比例关系），forbidden_claims 是否确实
   是错误结论。
2. **语义组等价性**：每组 4 种问法是否真的等价（同一意图、同一证据），
   有没有某一种问法额外要求了别的知识点。
3. **边界案例的 expected_status 判断**：特别是
   - `boundary.mp4570.junction_vs_ambient.01` 判 INSUFFICIENT_EVIDENCE 是否
     恰当（结温≠环境温度，缺功耗数据）；
   - `boundary.ambiguous_reference.01` 判 NEEDS_CLARIFICATION；
   - `boundary.mp4570.over_rating.01`（5A 请求）判 ANSWERED（以 3A 连续额定
     为依据给出否定结论）。
4. **query 自然度**：中英混合与口语问法是否自然、可被真实用户使用。

## 四、批准流程（用户批准后执行，本次不执行）

1. 用户阅读本摘要并按第三项抽查案例（可只抽代表性组）。
2. 用户明确批准后，agent 才可：为已审案例/span 置 human_reviewed=true，
   并在评审记录中写明审核人（用户本人）、日期与依据。
3. holdout_sealed 仅在此之后、且用户明确同意封存时方可置 true。
4. 未批准前保持上面的状态表述，S05 不得开始。
