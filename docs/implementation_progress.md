# LocalChipAdvisor Implementation Progress

## Execution record 2026-09-06

- Current step: S02 technical acceptance complete; stopped before S03; B06 human provenance pending
- Goal: establish a reproducible implementation ledger before feature fixes.
- HEAD before this step: `e2fedd6 Add executable CLI entrypoint`
- Branch: `feat/product-record`
- Existing uncommitted files before this step:
  - `9.6项目进度以及后续步骤.md` - untracked, preserve
  - `tests/test_packaging.py` ? untracked, preserve
- Applicable `AGENTS.md`: none found.
- Project interpreter: `D:\LocalChipAdvisor\.venv\python.exe`
- Python version: `3.11.16`
- CLI module entrypoint:
  - `python -m local_chip_advisor.cli --help` works
  - console-script packaging registration is not yet present
- Baseline pytest command:
  - `.venv\python.exe -B -m pytest -p no:cacheprovider --basetemp <fresh-temp-dir> -q`
- Baseline pytest result:
  - `114 passed`
  - `1 failed`
  - failure: `tests/test_packaging.py::test_pyproject_registers_cli_console_script`
  - cause: `KeyError: 'scripts'`
  - classification: known existing failure B01
  - new failures: none observed
  - environment failures: none observed

## Current data baseline

- Catalog database:
  - `data/processed/catalog.sqlite3`
  - file exists
  - database contents were re-audited by the S00 read-only audit script
- Current raw product-document scope observed:
  - MP4570 datasheet
  - MP4570 source metadata
  - MP4570 draft product record
  - MP4570 draft evidence record
- Do not infer publication/review authority from draft files alone.
- No product publication state will be changed during S00.

## Current model baseline

- `models/ollama/` exists on disk.
- Disk presence is not proof that a model is callable.
- Model API/runtime verification remains a later explicit step.
- No embedding-model verification has been performed in S00.

## Current implementation baseline

Confirmed existing:
- requirement parsing
- requirement review / follow-up / explicit confirmation
- LocalChipAdvisor application orchestration
- deterministic screening / recommendation pipeline
- SQLite catalog storage
- module CLI entrypoint

Not yet treated as implemented:
- document knowledge repository
- BM25 retrieval
- vector retrieval
- hybrid retrieval
- query-understanding layer
- evidence bundle
- document QA service
- answer validation pipeline
- retrieval evaluation pipeline
- knowledge snapshot activation / rollback

Dependency declarations do not count as implementation.

## Open issues B01-B10

- B01: packaging console-script registration is missing.
- B02: formal recommendation CLI formatting does not match the real FormalRecommendation object structure.
- B03: output-voltage tolerance is collected but not fully consumed by qualification rules.
- B04: thermal qualification does not fully model cooling / PCB / load applicability.
- B05: PRESENT surge does not yet have a complete transient qualification model.
- B06: published catalog state and draft/source review metadata require an audit trail explanation.
- B07: `INSERT OR REPLACE` persistence semantics must be replaced safely before relational expansion.
- B08: some read paths are mixed with schema initialization and must be separated.
- B09: project documentation contains stale historical statements and must be updated from evidence.
- B10: CLI confirmation does not yet show the full parsed requirement card before explicit confirmation.

## S00 status

Completed:
- S00.1: checked current git state, HEAD, source tree, interpreter, CLI module entrypoint.
- S00.2: ran a clean baseline pytest using a fresh temp directory and no pytest cache.
- S00.3: confirmed that the implementation ledger and audit script did not already exist.
- S00.4: created the implementation ledger.

### S00.5 read-only catalog audit

Audit script:
- `scripts/audit_baseline.py`
- opens the database through SQLite URI `mode=ro`
- does not use catalog repository initialization code

Safety checks:
- help exit code: `0`
- missing database exit code: `2`
- missing database was not created: `False`

Observed catalog state:
- `PRAGMA user_version = 0`
- tables: `evidence`, `products`
- products: `1`
- evidence: `3`
- `PRAGMA integrity_check = ok`
- foreign-key violations: `0`
- product: `MPS-MP4570@kb-dev-v1`
- publication status: `PUBLISHED`
- product evidence bindings observed: `5`
- reviewed evidence rows: `3/3`
- missing bound evidence references: `0`
- audit status: `OK`

Important interpretation:
- `user_version=0` is an existing populated schema, not evidence of an empty database.
- The audit confirms technical consistency only.
- It does not resolve B06 publication-history provenance.
- It does not authorize changing review or publication state.

### S00 final review

Verified before closing S00:
- implementation ledger reviewed
- audit script reviewed
- packaging red test preserved
- whitespace checks passed
- audit script syntax check passed
- no catalog database modification observed
- working tree contains only the expected untracked project artifacts

## S01 completion record

Completed:
- B01 packaging console-script registration:
  - added `[project.scripts]`
  - registered `local-chip-advisor = "local_chip_advisor.cli:cli_entrypoint"`
  - packaging regression test passes
- B02 formal recommendation CLI formatting:
  - reproduced the real `FormalRecommendation` object-structure failure first
  - formal output now reads `item.candidate.product_id`
  - formal output now reads deterministic checks from `item.candidate.evaluation.checks`
  - non-formal output continues to use `FlaggedCandidate.product_id` and `.issues`
- added regression coverage for:
  - one real formal recommendation
  - formal / near_match / needs_verification all present
  - all three buckets empty
- explicit yes-confirmation CLI behavior remains covered

Final S01 validation:
- full pytest: `118 passed`
- full pytest exit code: `0`
- `git diff --check`: passed
- changed-file Ruff:
  - `src/local_chip_advisor/cli.py`
  - `tests/test_cli.py`
  - `tests/test_packaging.py`
  - result: passed
- repository-wide Ruff still reports pre-existing lint debt outside the S01 change set
- mypy still reports pre-existing type-checking debt in:
  - `src/local_chip_advisor/cli.py`
  - `src/local_chip_advisor/ingestion/pdf_parser.py`
- no product data or catalog database changes were made during S01
- editable installation was not performed because direct console-command installation was not requested

## S02 audit record

### B06 publication provenance classification

Observed facts:
- `source.json` reports `human_reviewed=false` and `release_status=draft`
- the draft product remains `publication_status=DRAFT`
- all three draft evidence records already have `reviewed=true`
- published SQLite contains the same three evidence records with `reviewed=true`
- draft and published evidence payloads have no differing fields
- draft and published product payloads differ only in `publication_status`
- the source manifest, draft product, draft evidence, and processed SQLite catalog are not Git-tracked data artifacts

Conclusion:
- B06 is not currently an evidence-payload mismatch between draft and published storage
- the DRAFT-to-PUBLISHED product transition is consistent with the immutable publication-gate design
- the unresolved issue is publication provenance: the repository does not currently prove who reviewed/approved the evidence, when approval occurred, or what approval record authorized the published catalog state
- do not automatically change `source.json` to `human_reviewed=true`
- do not automatically revert the existing published catalog
- closing B06 requires an explicit human approval/provenance record or equivalent evidence

S02.1 backup:
- SQLite Backup API backup created and validated
- backup integrity check: `ok`
- foreign-key violations: `0`
- products: `1`
- evidence: `3`
- source database remained byte-for-byte unchanged during backup

## B07 completion record

Completed:
- reproduced the product `INSERT OR REPLACE` delete-and-insert behavior with a real SQLite foreign-key regression test
- confirmed that repeated product saves previously cascade-deleted dependent product rows
- replaced product `INSERT OR REPLACE` with explicit:
  - `INSERT ... ON CONFLICT (product_id, knowledge_base_version) DO UPDATE`
- reproduced the evidence delete-and-reinsert problem with a second real foreign-key regression test
- removed unconditional deletion of all evidence during ordinary repeated saves
- repeated saves of identical evidence now preserve the existing row and dependent links
- the same `evidence_id` plus `knowledge_base_version` with a changed payload now raises an explicit `evidence conflict`
- new evidence IDs are inserted without rewriting unchanged evidence rows

B07 validation:
- SQLite catalog focused suite: `10 passed`
- publication gate plus SQLite catalog joint regression: `13 passed`
- `src/local_chip_advisor/catalog/sqlite_store.py` Ruff: passed
- `git diff --check`: passed
- `tests/test_sqlite_catalog.py` still has 18 pre-existing Ruff findings in the existing test region; no reported Ruff finding is in the newly added B07 regression-test region

## B08 completion record

Completed:
- reproduced read-side schema mutation against an existing empty SQLite database
- confirmed missing database paths already raised `FileNotFoundError` without creating the parent directory or database file
- confirmed `load`, `find`, and `list` previously initialized `products` and `evidence` during ordinary reads
- split SQLite connections into explicit writable and read-only roles
- writable connections may create parent directories and initialize schema
- read-only connections require an existing database and use SQLite `mode=ro`
- read-only connections enable `PRAGMA query_only = ON`
- `load_published_catalog`, `find_published_candidates`, and `list_published_products` no longer call schema initialization
- ordinary reads no longer create directories, database files, or tables

B08 validation:
- focused read-side regression: `6 passed`
- SQLite catalog plus publication gate joint regression: `19 passed`
- `src/local_chip_advisor/catalog/sqlite_store.py` Ruff: passed
- `git diff --check`: passed

## S02 schema migration completion record

Completed:
- audited the live catalog schema read-only and confirmed `user_version=0` is a populated legacy schema, not an empty database
- locked the legacy-v0 structural fingerprint for:
  - `products`
  - `evidence`
  - composite primary keys
  - the composite evidence-to-products foreign key with `ON DELETE CASCADE`
- added explicit catalog migration API in:
  - `src/local_chip_advisor/catalog/sqlite_migrations.py`
- established `CURRENT_SCHEMA_VERSION = 1`
- defined v1 as a metadata-only baseline over the audited legacy structure
- added explicit migration reports containing:
  - `from_version`
  - `to_version`
  - planned `changes`
  - legacy-v0 detection
  - dry-run state
  - applied state
- implemented read-only dry-run behavior
- implemented explicit `user_version 0 -> 1` activation inside a write transaction
- repeated migration at v1 is idempotent and performs no write
- unsupported/future schema versions are rejected before dry-run can return a report
- malformed legacy-v0 schemas are rejected
- current-v1 databases must match the expected structural fingerprint
- both legacy-v0 and current-v1 preflight paths run `PRAGMA foreign_key_check`
- execution re-checks the legacy fingerprint and foreign-key integrity before activating v1
- migration failure due to foreign-key violations leaves `user_version=0`
- ordinary live catalog migration was not performed

Focused migration validation:
- migration suite: `10 passed`
- migration source and migration-test Ruff: passed
- explicit whitespace checks for untracked migration files: passed
- `git diff --check`: passed

Real database validation:
- S02 archive backup:
  - `backups/catalog-s02-20260906-091435.sqlite3`
- archive backup dry-run:
  - detected legacy-v0
  - reported `0 -> 1`
  - reported change: `set user_version from 0 to 1`
  - `dry_run=True`
  - `applied=False`
  - products remained `1`
  - evidence remained `3`
  - backup SHA-256 remained unchanged
- real migration was executed only on a temporary copy of the archive backup
- temporary copy migration:
  - v0 -> v1 succeeded
  - integrity check: `ok`
  - foreign-key violations: `0`
  - product rows preserved exactly
  - evidence rows preserved exactly
  - second migration was a no-op
  - second migration left file hash and database state unchanged
- the archive backup itself remained unchanged
- the live catalog was not migrated

S02 regression checkpoint:
- full pytest: `137 passed`
- full pytest exit code: `0`
- `git diff --check`: passed

## Next single priority action

`S02.38+`: define the audit/review record contract before adding audit or review tables.

The governing implementation plan requires explicit review provenance, but it does not define exact SQL fields. The next step must therefore lock the semantic contract first: reviewed object identity/type, review conclusion, basis/evidence, operator, and retained history. Do not fabricate a historical approval record for the existing published MP4570 catalog, and do not change `human_reviewed` or publication state without explicit evidence.

## Acceptance state

S00: completed.
S01: completed.
S02: technical acceptance complete; B06 human provenance pending. S03: not started.


## S02.54-S02.60 final acceptance (2026-09-06)

# LocalChipAdvisor：S02 技术验收与 S03 交接

日期：2026-09-06。**已停在 S03 之前，S03 未开始。**

## 验收结论

S02 的数据库安全基础、迁移机制、审核领域契约与后续持久化设计已完成技术验收。B06 历史人工审批来源仍待真实证据核对，不能宣称历史审批已经完成或所有发布资格已获确认。按指南，这限制正式资格扩展，不阻塞公开文档开发。

## 从哪里接手

- HEAD：`e2fedd6 Add executable CLI entrypoint`，保留用户既有未提交工作。
- 从 S02.54 接手；当时 ReviewRecord 已有对象、结论、依据、审核人和记录时间字段，但没有时间运行时校验。
- 本地尚无 S02.54 的无时区反例测试。
- 前序台账记录 S00、S01 完成，迁移检查点为全套 137 passed；这是历史数字。

## 本轮实际完成

### S02.54 / S02.55：时间契约 RED → GREEN

先加入无时区时间反例，实测 **1 failed、6 passed**，失败为 `DID NOT RAISE ValueError`。加入校验后 **7 passed**。

现在拒绝非 datetime 值及没有有效时区偏移的时间，接受带明确偏移的非 UTC 时间。不会自动猜时区或补造历史审批时间。

### S02.56 / S02.57：审核记录的有效性和版本

先验证缺少新字段和行为的失败，再实现以下约束；审核模型最终 **41 passed**。

- 新增必填 `review_id`、`object_version`，区分事件及对象版本。
- 对象 ID、版本、依据、审核人不得为空、纯空白或错误类型。
- 审核范围限定为 `document` / `evidence`，两种范围不互相授予资格。
- 结论限定为 `approved` / `rejected` / `pending` / `revoked`。
- 记录保持不可变；可用 `supersedes` 指向旧事件，拒绝空引用和自引用。
- 验证版本不同的对象保持不同身份，历史记录不会因新结论被修改。

这些属于结构和行为校验。非空依据不证明内容真实；创建对象不认证审核人、不写入数据库、不发布产品，也不自动解决 B06。事件唯一性、对象存在性、历史引用与有效资格仍需后续仓储核验。

### S02.58：数据库独立审查与修复

新测试先得到 **4 failed、1 passed**，暴露了保存/迁移的真实缺口。修复包括：

- 新路径首次创建为 v1；已有合法 legacy 保存时仍保持 v0，不暗中迁移。
- 拒绝未来版本、缺核心表、核心结构异常和外键坏链；不替异常库静默补表。
- 同一产品、同一 KB 版本内容不同，明确报 `product conflict`，要求新版本。
- 保留前序 UPSERT、证据冲突检查和额外关联表兼容性，重复保存仍保留链接。
- 迁移指纹补查列类型、NOT NULL、默认值，并增加完整性检查。
- 迁移事务内重新核对版本、结构和外键，失败不激活版本。
- 使用 `closing` 明确关闭生产连接，避免 Windows 文件句柄滞留。

迁移、原存储和新守卫联合验收：**32 passed**。

### S02.59：审核设计与后续实现边界

更新审核契约文档，明确追加事件、保留历史、撤销不删除历史、精确版本绑定、发布事件引用审核事件。

跨库链接设计采用 `catalog_snapshot_id + knowledge_base_version + evidence_id`，并要求核验登记文档、片段、原文区间、产品和版本；缺来源、错版本、断链等必须拒绝。

**实际 knowledge 仓储、审核 CLI、跨库查询校验留在 S05 实现**；快照激活及缓存失效生命周期在 S17。这些没有冒充已完成。S02 完成语义/接口设计，符合指南的阶段边界。

### S02.60：最终验收

| 检查 | 实际结果 |
|---|---|
| 全套 pytest | **184 passed in 3.68s** |
| 审核模型 | 41 passed |
| 迁移、存储、新守卫 | 32 passed |
| 本轮相关 3 个生产模块、3 个测试文件 Ruff | 通过 |
| git diff --check | 通过 |
| 全仓库 Ruff | **未通过：109 条问题**，位于本轮未修改文件 |
| 全仓库 mypy | **未通过：10 条错误**，位于 cli.py、ingestion/pdf_parser.py |

全仓库 lint/type 问题所在文件和类别与原台账的欠账一致；本轮没有扩展到无关清理。不能将 pytest 全绿写成“所有检查全绿”。

## 真实数据库验证

对已有归档备份做只读预演，再用 SQLite Backup API 创建独立临时副本执行迁移：

- 预演报告 `0 → 1`、变更摘要和 `applied=false`。
- 临时副本迁移成功，完整性检查 `ok`，外键检查无违例。
- **1 款产品、3 条证据的全部行内容迁移前后一致。**
- 第二次迁移无变化、`applied=false`，文件哈希不变。
- **正式库及原归档备份哈希均未改变；正式库仍为 v0。**

正式库 SHA-256：`3b09ce24254ceb13f5a947e2e11f7f13b673ff79cf86b70da1962099257b12d4`

归档备份 SHA-256：`a2a1cad3da6d569ac8842236036273353196bf2c444dd367f250a24ee1ae6cc9`

## 本轮文件清单

- `src/local_chip_advisor/domain/review.py`：审核校验、版本、历史标识。
- `tests/test_review_audit_models.py`：审核行为测试、旧夹具必填字段更新。
- `src/local_chip_advisor/catalog/sqlite_migrations.py`：完整指纹、完整性检查、连接关闭。
- `src/local_chip_advisor/catalog/sqlite_store.py`：保存守卫、产品冲突、连接关闭。
- `tests/test_s02_database_guards.py`：新增数据库回归测试。
- `docs/review_audit_contract.md`：可执行契约及 S05 交接。
- `docs/implementation_progress.md`：完成记录与最新停止点。

保留既有未提交工作；未提交或推送 Git，未改变实际产品发布/审核状态。

## B06 人工缺口

现有 `PUBLISHED` / `reviewed=true` 本身不能证明谁在何时审核了哪些资料。仍需真实审核者、资料版本、参数条件和可追溯审批依据。

没有自动设置 `human_reviewed=true`，没有捏造审核人、时间或依据，也没有自动回退已发布产品。状态保持 **pending human provenance**。

## 停止点

S03 未开始，未修改工程规则和 required rule 集合。下一次先建立“需求字段 → 单位 → 对应规则 → 所需证据 → 未覆盖状态”的矩阵，再处理输出误差、热工况和浪涌边界。


## Authoritative next single priority action

S03: not started. Await user continuation before implementing the requirements-to-rule coverage matrix. Earlier next-action entries are historical checkpoints superseded by this record. B06 remains pending human provenance.

## S03 completion record (2026-09-06)

# LocalChipAdvisor：S03 完成（需求字段 → 工程规则完整覆盖）

日期：2026-09-06。**S03 全部子项完成并验证；已停在 S04 之前。**

指南 S03 章节（`9.6项目进度以及后续步骤.md` 361-378 行）验收原则全程遵守：
±2% 无证据不得 formal；温度数值够但自然对流条件不明不得 formal；Absolute
Maximum 不作为正常工作 PASS 依据。新增的 UNKNOWN 是预期语义，不是回归。

## S03-A：输出误差规则入口（UNKNOWN-only）

- `check_output_tolerance` 只输出 UNKNOWN：无结构化 total-output-error 能力、
  无决定性精度证据、`vout.range` PASS 与 feedback-reference 电压都不构成精度
  guarantee。
- 先 RED（新增测试断言 rule 存在并 UNKNOWN）后 GREEN。

## S03-B：vout.tolerance 接入正式门

- screening 开始发射 `vout.tolerance`，`DEFAULT_REQUIRED_RULE_IDS` 由 6 条扩为
  **7 条**。
- 旧演示现在多输出 `vout.tolerance` UNKNOWN issue 是预期变更；issue 测试按
  rule_id 重建索引并断言 `{vout.tolerance, iout.peak, thermal.ambient}`。

## S03-C：需求字段覆盖守卫

- `REQUIREMENT_FIELD_COVERAGE`（screening.py）为全部 16 个 RequirementCard
  字段声明去向：hard rule / 结构性适用条件 / context-only(`()`)。
- `tests/test_screening_coverage.py` 断言字段键 == `RequirementCard.model_fields`
  且 rule 集合 == `DEFAULT_REQUIRED_RULE_IDS`——"用户条件已收集但无规则消费"
  从此是测试失败而非静默状态。

## S03-D：热资格结构化条件匹配

- 新增 `ThermalCoolingMode`（NATURAL_CONVECTION / FORCED_AIRFLOW）：需求侧
  `RequirementCard.cooling_method`、产品侧 `ambient_cooling_method`。
- `check_ambient_thermal` 重写为 regime 匹配，物理规则而非文本相等：
  - NC rating 覆盖同数值内 NC 与 FA 请求（NC 是更难 regime）；
  - FA rating 只覆盖 FA 请求；任一侧 regime 缺失或有 gap → UNKNOWN，绝不 FAIL；
  - 超过 NC-rating 的 FA 请求：NC rating 不构成约束 → UNKNOWN（不是 FAIL）。
- `thermal_conditions` 声明为 context-only，不再参与 PASS/FAIL 决策。

## S03-E：峰值电流 fallback 适用性

- `check_peak_output_current` 的 continuous-rating fallback 增加 regime +
  ambient 门控：rating regime（`iout_continuous_cooling_method`）与请求 regime
  均须结构化为已知并匹配，否则 UNKNOWN；匹配 regime 内再核对请求环境温度不超
  rating 声明值。

## S03-F：surge 回归锁定

- 7 个回归测试确认 `PRESENT` → UNKNOWN（附 Absolute Maximum 提醒）、
  `NONE_EXPECTED` → PASS 绑定 vin_max 证据、显式 unknown → UNKNOWN；
  S03 未削弱任何既有边界。drift locks 首跑即 GREEN。

## S03-G：最终门禁

| 检查 | 实际结果 |
|---|---|
| 全套 pytest | **212 passed in 2.79s** |
| 改动文件 Ruff | 通过（本 S03 修复 71 条：Decimal 整数字符串、import 排序、注解引号） |
| 全仓库 Ruff | 未通过：**76 条**，全部位于与 HEAD 逐字节一致的文件（既有债务，S03 零新增） |
| 全仓库 mypy | 未通过：**10 条**，全部位于 cli.py、ingestion/pdf_parser.py（与 S02.60 台账同位置同数量，S03 零新增） |
| git diff --check | 通过 |
| untracked 文件空白检查 | 通过 |

正式覆盖率矩阵：`docs/requirements_coverage.md` 已由 pre-S03 冻结基线升级为
S03 完成态（基线版本保留在 git commit `02df2a9`）。

## 本轮实际变更文件

- `src/local_chip_advisor/domain/models.py`：`ThermalCoolingMode`；
  RequirementCard 新增 `cooling_method`。
- `src/local_chip_advisor/domain/product.py`：新增 `ambient_cooling_method`、
  `iout_continuous_cooling_method`（后者由并行外部 actor 加入，已采用）。
- `src/local_chip_advisor/domain/product_rules.py`：`check_output_tolerance`
  UNKNOWN-only；`check_ambient_thermal` regime 匹配重写；
  `check_peak_output_current` fallback regime + ambient 门控。
- `src/local_chip_advisor/domain/decision.py`：`DEFAULT_REQUIRED_RULE_IDS` 7 条。
- `src/local_chip_advisor/requirements.py`：`RequirementParsePayload` 新增
  `cooling_method`（含 description，供 AI parser 结构化输出）。
- `src/local_chip_advisor/screening.py`：`REQUIREMENT_FIELD_COVERAGE` +
  evaluate_candidate 接线（thermal / peak 均收 `cooling_method`；
  peak 另收 `ambient_max_c`）。
- `tests/`：test_product_rules.py（thermal regime 矩阵、tolerance、surge
  回归）、test_screening.py（confirmed_requirements 增 cooling_method、
  ambient_rated fixtures、热资格应用级测试）、test_screening_coverage.py（新）、
  test_recommendation.py（issue 集合按 7 条规则更新）。

## 并行外部修改（已采用，非本会话改动）

- product.py / product_rules.py / test_product_rules.py 在会话期间被并行 actor
  修改（`iout_continuous_cooling_method`、`requested_cooling_method` /
  `requested_ambient_max_c` 签名演进及配套测试），已核对签名一致性并集成；
  HEAD 亦被推进至 `02df2a9`（S02 检查点工作被一次性提交）。
- 全部 212 个测试通过证明集成后语义一致。

## 约束保持

- 解释器始终为 `.venv\python.exe`；未提交、未 push、未删除数据；
  未改变 MP4570 发布/review 状态；未触碰 live catalog（v0 保持）；
  未降低任何门槛；`vout.tolerance`、未声明 regime 的热/峰值路径保持 UNKNOWN，
  无 UNKNOWN 被改写成 PASS；未留下 `NotImplementedError`。

## 停止点

**S03 完成。S04 未开始。** 下一次从 S04 继续；B06 仍为 pending human
provenance。Earlier next-action entries are historical checkpoints superseded
by this record.

## S03-G 复核记录（同日，独立复验）

上节完成记录的 ruff/mypy 数字经独立复验，追加文件级证据与口径说明。

复验命令口径：

- pytest：`.venv\python.exe -B -m pytest -p no:cacheprovider --basetemp <fresh-temp> -q`
- ruff：`.venv\python.exe -m ruff check --no-cache src tests`
- mypy：`.venv\python.exe -m mypy --cache-dir <fresh-temp> src/local_chip_advisor tests`

### 复验结果

| 检查 | 复验实际结果 |
|---|---|
| 全套 pytest | **212 passed in 3.11s**（台账 2.79s 为同内容运行的 wall-clock 抖动） |
| 全仓库 ruff | 未通过：**76 条 / 10 个文件**，与上节记录数字一致 |
| mypy src-only | **10 条**（cli.py 6、ingestion/pdf_parser.py 4），与记录及 S02.60 台账同位置同数量 |
| mypy src+tests | **101 条 / 15 个文件**；src 10 条同上，tests 91 条全部为既有未注解测试债务 |
| git diff --check | 通过 |

### ruff 76 条分布（全部位于 S03 未修改文件）

- tests/test_requirements.py 41、tests/test_sqlite_catalog.py 24、
  tests/test_catalog_io.py 3、tests/test_advisor.py 2
- tests/test_ranking.py 1、tests/test_publication_gate.py 1、
  tests/test_product_record.py 1
- src/local_chip_advisor/ollama_requirements.py 1、
  src/local_chip_advisor/advisor.py 1、src/local_chip_advisor/catalog/io.py 1

S03 改动文件（domain/、decision.py、screening.py、requirements.py、
test_product_rules.py、test_screening.py、test_screening_coverage.py、
test_recommendation.py）ruff 均 0 条。

### mypy 101 条口径说明

上节记录“全仓库 mypy 10 条”实际为 **src-only 口径**（该命令只检查
`src/local_chip_advisor`）。若按全仓库（src + tests）口径复验为 **101 条 /
15 个文件**，其中：

- src：cli.py 6（no-untyped-def）、pdf_parser.py 4 —— 与记录一致；
- tests：91 条，根因是历史测试文件的未注解 fixtures/helpers
  （test_cli.py 30、test_publication_gate.py 16、test_review_audit_models.py 15、
  test_screening.py 11、test_recommendation.py 3、test_pdf_parser.py 3、
  test_advisor.py 3、test_product_record.py 3、test_ollama_requirements.py 2、
  test_s02_database_guards.py 2、test_ranking.py 1、test_sqlite_catalog.py 1、
  test_catalog_io.py 1，合计 91），模式为 no-untyped-def /
  no-untyped-call / arg-type 级联，均非 S03 引入的语义错误；S03 改动文件
  mypy 0 条。

全仓库 lint/type 欠账与 S02.60 台账同源同类；S03 零新增，未扩展到无关清理。
不能将 pytest 全绿写成“所有检查全绿”。

## S04 完成记录（2026-09-06，agent 自检，未人审）

**状态：S04 TECHNICAL DATASET COMPLETE / HUMAN REVIEW PENDING / S04 NOT YET
FULLY ACCEPTED / S05 NOT STARTED**

S04 交付内容（全部为新增文件，未改动任何既有代码/数据）：

- `evaluations/corpus_manifest.json`：4 份官方 datasheet（MP4570 Rev.1.01
  2017-01-04；TPS54331 SLVS839H 2023-10；TPS562201+TPS562208 SLVSD91D
  2024-09；LT8610 Rev.D 2024-08），source_id + SHA-256 + 页数，哈希已逐文件
  重算核对；`data/raw/` 下 PDF 本体由 .gitignore 排除，不入库。
- `evaluations/topic_inventory.md`：21 主题 × 4 芯片 PRESENT/NOT_FOUND/
  AMBIGUOUS 矩阵。逐行复核更正一处扫描漏报：MP4570 output_range 实为
  PRESENT（P4 推荐工作条件行 1V to 0.9·VIN），初始标 NOT_FOUND 是关键词
  扫描错误，已在清单与 manifest 中更正并注明。
- `evaluations/cases/`：README、annotation_guide（数据契约：证据优先作者
  顺序、alternative=OR/requirement=AND、split 硬规则、verbatim 伪影规范化
  规则、评审门）、review_summary（人工评审材料）、dataset_manifest（计数）。
- 数据规模：**普通 50 组 × 4 = 200 条（dev 30 组 / holdout 20 组）；
  边界 10 组 × 4 = 40 条（dev 7 / holdout 3）；gold spans 79 条**；
  状态分布 ANSWERED 208 / INSUFFICIENT_EVIDENCE 24 / NEEDS_CLARIFICATION 4 /
  OUT_OF_SCOPE 4。
- 首批 10 个语义组按指南锁死为 dev（validator 常量锁定组 ID，含防泄漏
  断言）；holdout 未经人审批准保持 `holdout_sealed=false`。
- `tests/test_s04_evaluation_dataset.py`：9 项确定性结构断言（无网络/无
  模型/无 Chroma/无 Embedding），含 manifest 哈希落地校验、页码边界、无
  chunk_id（chunk 映射留待 S05/S07）、组不跨 split、四语言齐备、无死 span、
  human_reviewed 恒 false 门禁；S04.13 起按 dataset_manifest 核对最终计数。

| 检查 | S04 实际结果 |
|---|---|
| 全套 pytest | **221 passed in 2.18s**（S03 基线 212 + S04 新增 9） |
| S04 定向 pytest | 9 passed（每次数据变更后重跑） |
| span verbatim 回查 | **79/79** 逐字命中原文提取（`D:\Cache\Temp\s04_verbatim_check.py`；空白归一 + 软连字符 U+00AD 伪影剔除后匹配；含 MP4570 原文笔误 "it will turns on"、"50%xRFF"、"25%xRFE" 逐字保留） |
| ruff（tests+src） | 76 条 / 10 个文件 —— 与 S03 基线完全一致，**S04 零新增**（新文件单独检查 All checks passed） |
| ruff（scripts/） | 15 条（smoke_mp4570 8、audit_baseline 6、smoke_models 1）—— S03 基线口径未含 scripts/，为既有债务，非 S04 引入 |
| mypy src-only | 10 条 / 2 文件（cli.py、pdf_parser.py）—— 与 S02.60/S03 台账一致，S04 零新增 |
| 文件卫生 | 12 个新文件全部 UTF-8 无 BOM、LF、无尾随空白（validator + 独立脚本双重检查） |
| git diff --check | 通过（S04 新文件为 untracked，以文件卫生检查代替；tracked 文件 diff --check 通过） |
| live catalog / MP4570 发布与评审状态 | 未改动（git status 确认，仅新增 untracked S04 文件与既有 9.6 文档） |

### S04 期间发现并处理的问题（如实记录）

1. `evaluations/` 原仅 .gitkeep；S04 全部文件为新增。
2. MP4570 output_range 扫描漏报（见上）——已更正，并保留更正说明。
3. TI/ADI 转储的提取伪影：行尾空格（rstrip）、断行软连字符 U+00AD
   （LT8610 转储 "pre\xad vent"，需连同 CRLF 一并剔除）——规范化规则已写入
   annotation_guide；verbatim 其余部分逐字一致。
4. TPS54331 OVTP span 初稿超 400 字符上限，拆为两条互补 requirement
   （purpose / thresholds），dev 组引用同步更新。
5. 环境问题（与 S04 无关，仅记录）：`.pytest_cache\v\cache` ACL 拒绝访问，
   pytest 出缓存警告但不影响结果；S04 定向运行用 `-p no:cacheprovider` 规避。
6. TPS54331 转储确认无 "hiccup" 表述（grep 零命中），
   `boundary.model_confusion.01` 的 INSUFFICIENT_EVIDENCE 判定据此成立。

### 人工评审门（待用户）

- 评审材料：`evaluations/cases/review_summary.md`（agent 自检清单 + 4 项
  人工评审要点 + 批准流程）。
- 用户批准前：全部 human_reviewed=false、holdout_sealed=false，状态表述
  如上；未审核案例不得进入最终成绩（S16 口径）。
- 用户批准后按 review_summary 第四节流程置位，再由人补评审记录。
- **S05 未开始**：未建 knowledge.sqlite3、未做形式化分块、未装/运行
  Chroma、未调 Ollama/Embedding、未做任何检索/问答接线。


## S03 复核修订 + S04 复核修订（2026-09-06，独立复核后同日完成）

独立复核（用户提供的外部复核报告）指出：S03 仍有工况适用性缺口、S04 有
1 条 span 页码错误且多组四种问法语义不等价。本节记录针对性的修订。

### S03 修订（保守化 UNKNOWN-first + 行为级覆盖）

- `check_continuous_output_current`：请求电流未超额定数值不再 PASS——冷却、
  环境、VIN、PCB、负载、功耗适用性未结构化且无证据绑定时一律 UNKNOWN；
  超限仍 FAIL（数值上限仍可拒绝）。
- `check_peak_output_current`：连续 fallback 与显式峰值路径同理：数值内
  UNKNOWN，超限 FAIL；UNKNOWN 不再挂 evidence_ids（不再暗示证据已证明）。
- `check_ambient_thermal`：cooling regime 相容且数值内不再 PASS——PCB/
  heatsink/负载/功耗未结构化时 UNKNOWN；用户 regime 下明确超额定仍 FAIL。
- `REQUIREMENT_FIELD_COVERAGE` 重构为三分类：`QUALIFICATION_INPUT_RULES`
  （实际影响判定）、`CONTEXT_CLARIFICATION_FIELDS`（raw_request/
  vin_nominal_v/thermal_conditions，追溯与澄清用）、`PROCESS_METADATA_FIELDS`
  （confirmed_by_user），结构漂移守卫不变。
- `tests/test_screening_coverage.py` 由声明级升级为行为级：逐字段
  fingerprint 用例（改变该字段必须改变对应规则的结果），并覆盖
  "thermal_conditions 改变不影响判定"（上下文字段不得成为决策输入）。

### S04 修订（页码 + 组内问法等价 + 页级校验入库）

- `tps54331.soft_start.01.s1` 页码 10 → 11（独立 PyMuPDF 按页回查命中）；
- validator 新增 `test_s04_gold_spans_are_verbatim_on_declared_physical_pages`：
  79 条 span 的 verbatim_text 必须在**声明页**内逐字命中（pymupdf 直读
  PDF，软连字符伪影规范化后匹配），79/79 页级命中；
- 41 个语义组（104 条 case）的 query 语义对齐：同组四种表达统一询问同一
  范围（触发+恢复阈值成对、完整输入范围、基准精度≠输出精度、开关限流≠
  输出能力、待机电流≠关断电流、定性 EMI 措施≠性能评价等）；仅修改
  `query` 字段，其余字段经脚本断言逐字节不变；9 组维持原样；
- 新增 `evaluations/cases/semantic_scope_review.json`：技术预审清单
  （review_kind=technical_pre_review，human_reviewed=false，50 组全覆盖，
  corrected 41 / no_change 9，每组一条统一问题范围），validator 强制
  清单与数据集组集合精确一致。

### 复验结果

| 检查 | 结果 |
|---|---|
| 全量 pytest | **242 passed in 2.26s** |
| S04 定向 pytest | 11 passed（含页级 verbatim 与 scope-review 门禁） |
| ruff src+tests | 76 条，与 S03 基线逐文件一致，修订文件 0 新增 |
| git diff --check | 通过 |

状态表述不变：**S03 修订完成待验收；S04 TECHNICAL DATASET COMPLETE /
HUMAN REVIEW PENDING / S04 NOT YET FULLY ACCEPTED / S05 NOT STARTED**。
human_reviewed 与 holdout_sealed 仍全部 false，等待人工验收。
