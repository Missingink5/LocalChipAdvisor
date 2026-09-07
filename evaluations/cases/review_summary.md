# S04 评审摘要（Human Review Gate Material）

日期：2026-09-06
状态：**agent_checked=true；human_reviewed=true；holdout_sealed=true**
最终状态表述：**S04 FULLY ACCEPTED / HOLDOUT SEALED / S05 NOT STARTED**

本文件是人工评审门（S04.12）的材料。机器可检查的不变量已由
`tests/test_s04_evaluation_dataset.py` 强制执行（11 项测试全绿）；语义质量
由下面的 agent 自检清单 + 人工评审项覆盖。**任何 human_reviewed 都必须由
`human_review.json` 中的用户批准批次支持；未列入批次的记录不得进入最终成绩。**

## 一、数据集规模（validator 实算，2026-09-06）

| 项 | 数量 |
|---|---|
| 语料文档（corpus_manifest.json） | 4 份官方 datasheet |
| 普通语义组 | 50 组（dev 30 / holdout 20） |
| 普通案例 | 200 条（每组 4 种语言表达） |
| 边界组 | 10 组（dev 7 / holdout 3） |
| 边界案例 | 40 条 |
| gold spans | 83 条 |
| 状态分布 | ANSWERED 208 / INSUFFICIENT_EVIDENCE 24 / NEEDS_CLARIFICATION 4 / OUT_OF_SCOPE 4 |

## 二、Agent 自检清单（已执行并记录）

1. **来源真实性**：4 份 PDF 均从官方链接下载，SHA-256 已重算核对；
   manifest 中 `local_file` 逐文件存在且哈希一致（validator 强制）。
2. **verbatim 逐字回查**：仓库内 validator 使用 PyMuPDF 对 83/83 span
   按其声明的 1-based 物理页范围逐字回查；只处理标注指南允许的换行和
   软连字符提取伪影，不允许回退到整份 PDF 搜索。含原文笔误逐字保留：
   MP4570 "it will turns on again"、
   "50%xRFF"、"25%xRFE"、"following close loop operation"。
3. **页码锚点**：每个 span 的 `pdf_page_start/end` 为 1-based 物理页；
   validator 同时校验页码范围、PDF 实际页数及原文必须出现在声明页内。
4. **主题清单复核**：关键词扫描 + 逐页人工复核。发现并更正一处扫描漏报
   （MP4570 output_range 实为 PRESENT，P4 推荐工作条件行 1V to 0.9·VIN）。
   NOT_FOUND/AMBIGUOUS 主题只产生证据不足案例，不产生"功能不存在"断言。
5. **split 隔离**：语义组不跨 split、不跨 normal/boundary；首批 10 组永久
   dev（validator 常量锁定组 ID）；同组 4 表达语言集合恰为
   {zh_formal, zh_colloquial, en, zh_en_mixed}。
6. **替代/互补语义**：alternatives 只用于同知识点多处表述（如 MP4570 输入
   范围 P1 两处）；跨知识点用多条 requirement（AND 语义），案例中
   requirement_id 唯一。
7. **评审标记**：7 个案例批次覆盖全部 60 个组、240 cases 和 83 spans；
   文档审核覆盖 4 份 datasheet。全部标记为 true，`human_review.json`
   记录审核人、日期、依据和精确 ID 清单。
8. **问法范围技术预审**：`semantic_scope_review.json` 覆盖全部 50 个普通组；
   第二轮逐条返修后 48 组标记为 corrected，2 个输出电压设定组保持
   no_change。该清单仍是 agent 技术预审，不构成人工批准。

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

## 四、批准与封存规则（已执行）

1. 前三批由用户逐批审阅并明确批准；第四批批准时，用户同时预授权后续批次
   按相同的逐组复核、返修和验证流程执行。
2. 每批只把实际核对的案例/span 置 `human_reviewed=true`，并在
   `human_review.json` 写明审核人、日期、依据与精确 ID。
3. 全部 60 组、240 cases、83 spans 和 4 份文档通过后，才把
   `holdout_sealed` 置 true。
4. holdout 封存后不得依据其评测结果反向修改 query 或金标；S05 尚未开始。

## 五、人工审核批次记录

### Batch 01（2026-09-07，project_owner）

- 范围：首批 10 个永久 dev 语义组，共 40 cases、15 spans；
- 结论：用户明确回复“按建议处理并通过第一批”；
- 返修：`tps54331.light_load.01` 的口语问法明确为峰值电感电流与 COMP 条件；
  `tps54331.thermal_shutdown.01` 改为原文支持的“超过 165°C 停止开关、
  降到 165°C 以下重新执行上电流程”，不再声称存在两个独立且相同的阈值；
- 机器门禁：审核清单、case 标记和 span 标记必须精确一致；未审核记录保持 false；
- 未执行：document 级批准、其余 40 个普通组、10 个边界组、holdout 封存和 S05。

### Batch 02（2026-09-07，project_owner）

- 范围：第二批 10 个 dev 普通语义组，共 40 cases、18 spans；
- 结论：用户明确回复“按建议返修并通过第二批”；
- 返修：补全 PG 上拉电阻原文、SYNC 输入电平原文和 BIAS 供电切换条件；
  分离轻载 pulse-skipping 与低 FB 频率折返的触发语义；收窄 OCP 问法到
  当前证据支持的保护类型与折返；新增 JESD51-7 四层 PCB 热阻测试条件 span；
- 当前累计：20 个普通组、80 cases、33 spans 已审核；
- 未执行：document 级批准、其余 30 个普通组、10 个边界组、holdout 封存和 S05。

### Batch 03（2026-09-07，project_owner）

- 范围：剩余 10 个 dev 普通语义组，共 40 cases、15 spans；
- 结论：用户明确回复“按建议返修并通过第三批”；
- 返修：OVTP 禁语改为禁止把动作阈值当作正常调节范围；EN 问法明确
  1.25V 对应 3µA 迟滞电流的加入条件，并保留浮空内部上拉的原文边界；
  TPS562201 Eco 禁语收窄为不得把只针对 TPS562201 的段落直接套用到 TPS562208；
- 当前累计：30 个 dev 普通组、120 cases、48 spans 已审核；
- 未执行：10 个边界组、20 个 holdout 普通组、document 级批准、holdout 封存和 S05。

### Batch 04（2026-09-07，project_owner）

- 范围：7 个 `boundary_dev` 组，共 28 cases；新增并审核 3 个 span，另审核
  2 个既有边界 span；
- 关键修复：MP4570 短路由错误的 `INSUFFICIENT_EVIDENCE` 改为有证据的
  `ANSWERED`，并同步修复 `topic_inventory.md`；TPS562201 OVP 保持证据不足，
  但用 P5 表头/VUVP 片段证明歧义；热判断补齐公式和测试板条件；型号混淆
  案例加入两颗产品各自的保护证据；
- 当前累计：37 个组、148 cases、53 spans 已审核；
- 未执行：20 个 holdout 普通组、3 个 boundary_holdout 组、document 级批准、封存和 S05。

### Batch 05（2026-09-07，project_owner 预授权）

- 范围：前 10 个 holdout 普通组，40 cases、16 spans；
- 返修：TR/SS 禁语、LT8610 MSE 封装/裸露焊盘条件、1.7µA 电流单位、
  RT 公式单位说明和 EMI 口语范围；
- 门禁通过后进入 Batch 06。

### Batch 06（2026-09-07，project_owner 预授权）

- 范围：剩余 10 个 holdout 普通组，40 cases、13 spans；
- 返修：TPS54331 输入旁路电容证据扩展；TPS562201 旧版关断电流问法；
  MP4570 EN 跨页残句收窄为完整支持的高压上拉/150µA 条件；
- 50 个普通组至此全部审核完成。

### Batch 07（2026-09-07，project_owner 预授权）

- 范围：3 个 `boundary_holdout` 组，12 cases、1 个新增审核 span；
- 返修：MP4570 5A 请求明确为超出 3A 连续额定，额外散热不能改写额定值；
- 60 个组、240 cases、83 spans 至此全部审核完成。

### Document Review 01 与封存（2026-09-07）

- 核对 4 份 datasheet 的官方厂商域名、型号范围、修订号、本地页数和
  SHA-256；4/4 页数与哈希匹配；
- 修正 corpus manifest 中关于 MP4570 短路、TI PG/SYNC 缺失的陈旧或过强备注；
- 全部文档 `human_reviewed=true`，`holdout_sealed=true`；封存后不得依据
  holdout 评测结果反向修改 query 或金标；S05 未开始。
