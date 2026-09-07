# MVP 交付记录

日期：2026-09-07。

- 复用 S05 知识库：4 份已审核 PDF、1561 个质量为 OK 的文档片段。
- 本地 embedding：`qwen3-embedding:0.6b`，1024 维，Chroma cosine 索引。
- 检索：原问题 dense + BM25 中英术语扩展 + RRF；产品范围过滤、重复页眉过滤，最多 12 块/11000 字符。
- 早期 MVP 仅做 ID 选择 + 第二次模板校验，不生成自然语言；旧交付状态记录在 `reports/mvp/dev_retrieval_v3.json`。

## 澄清后直接中文回答（S06 起）

按 `MVP修复指南_澄清对话与有证据中文回答.md` 的 R0–R6 顺序交付：
页面主区域直接显示简短中文答案与事实级证据；逐事实审核 + 一次定向修订；
每会话独立的 ConversationState 串接追问与澄清；不修改 sealed gold/holdout、
工程阈值或产品发布状态。

新增模块：

| 文件 | 角色 |
|---|---|
| `src/local_chip_advisor/mvp/contracts.py` | Pydantic 数据契约（UserTurn、Claim、AnswerDraft、AnswerReview、EvidenceBundle、ClarificationRequest 等） |
| `src/local_chip_advisor/mvp/answer_validation.py` | 硬校验：结构、ID 归属、anchor 原文、数字绑定、单位/角色/值等级、缺失值 |
| `src/local_chip_advisor/mvp/prompts.py` | 理解、生成、审核三类提示词与 JSON Schema |
| `src/local_chip_advisor/mvp/chat_client.py` | Ollama 客户端，按阶段分配 num_predict，处理 think / 解析失败 |
| `src/local_chip_advisor/mvp/answering.py` | 草稿→硬校验→审核→修订→最终渲染的完整流水线 |
| `src/local_chip_advisor/mvp/conversation.py` | 会话状态机，澄清/选项/换题/产品继承 |
| `src/local_chip_advisor/mvp/service.py` | `handle_turn` 多轮入口与 `ask` 单轮兼容 |
| `mvp_app.py` | Streamlit 聊天式 UI，每浏览器会话独立状态 |
| `scripts/ask_mvp.py` | CLI 新增 `--interactive` |
| `scripts/acceptance_matrix.py` | 真实多题验收脚本 |
| `scripts/smoke_mvp_conversation.py` | 多轮澄清烟测脚本 |

修复前后行为对比：

| 入口 | 旧版（2026-09-07 上午） | 修复后 |
|---|---|---|
| `MP4570 太热会自己停吗？` | 固定提示 “找到以下原文说明，请结合原文条件阅读” 或 MODEL_ERROR | 直接给出“会。典型约 170°C 触发、160°C 以下恢复、迟滞 10°C”，并附引用 `[1] [2]` |
| `太热会自己停吗？` | 直接 NEEDS_CLARIFICATION，丢失原主题 | 追问型号；用户答 `MP4570` 后继续原问题 |
| `MP4570 怎么样？` | 直接 NEEDS_CLARIFICATION | 列出主题选项；选 `过温保护` 后检索并回答 |
| `不是3A是300mA` | 旧测试断言为 `iout_continuous=0.3`（静默套用持续角色） | 追问持续/峰值/限流；只有带明确角色的修正才直接落库 |
| TPS562201 OVP | 仅给出一段 VUVP 文字 | 直接给出“资料不足”的具体拒答说明 |

测试矩阵：383 passed（修复前 353 passed + 30 新增）。

## 真实验收（acceptance_matrix）

`reports/mvp/answer_fix/acceptance_matrix.json`：

- 14 个跨主题问题，覆盖 MP4570 过温 / 软启动 / 轻载 / PG / 60V、
  TPS54331 软启动 / 轻载 pulse-skipping / 输入范围、
  TPS562201 UVP / OVP 拒答、中英混合、英文、澄清追问与无条件安全承诺拒答。
- 每一题记录 `answer_text`、`status`、`citations`、`claim_count`、
  `unanswered_scopes`、`elapsed_seconds`。
- 报告中的 `summary.passed / summary.failed` 直接对应页面能交付给用户的
  答案质量，不是 pytest 总数。

详细会话日志见 `reports/mvp/answer_fix/smoke_conversation.json`。

## 注意事项

- 工程合格判定仍由选型主链处理；MVP 仅做文档问答。
- 当前 `MP4570 软启动时间怎么设置？` 等问题在公开语料里仅有 enable/SS
  引脚与一段叙述，无精确数值；这会被标为 PARTIAL_ANSWER 或
  INSUFFICIENT_EVIDENCE，是真实资料状态，不是代码缺陷。
- 模型 `num_predict` 已经按阶段分配（理解 600 / 生成 2200 / 审核 900），
  过长会被截断并按 MODEL_ERROR 处理；当前没有观察到重复出现。
