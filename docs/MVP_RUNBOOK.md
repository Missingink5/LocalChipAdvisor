# LocalChipAdvisor MVP 运行手册

## 启动

双击项目根目录的 `启动MVP.cmd`。脚本会启动本地 Ollama，并在
`http://127.0.0.1:8501` 打开 Streamlit 页面。首次聊天模型加载可能需要数秒。

PowerShell 启动方式：

```powershell
Set-Location D:\LocalChipAdvisor
.\scripts\start_mvp.ps1
```

## 真实中文问答（默认入口）

聊天模型现在为支持文档检索的事实级回答提供生成、逐事实审核与一次定向修订；
页面主区域直接显示针对问题的简短中文答案，附带 `[1] [2]` 来源编号。
原文默认折叠，编号在 `**来源**` 折叠区展开。

## 交互模式（推荐）

```powershell
.\.venv\python.exe .\scripts\ask_mvp.py --interactive
```

输入用户消息，模型直接返回简短中文回答；若信息不足则会追问，回复对应选项
或自由文字都能继续原问题。`/new` 重置会话，`/exit` 退出。

## 单轮 JSON

```powershell
.\.venv\python.exe .\scripts\ask_mvp.py --query "MP4570 太热会自己停吗？"
```

仅查看检索结果时添加 `--retrieval-only`。该模式不代表证据已经足够回答。

## 能力与边界

当前语料为四份已审核 datasheet，支持 MP4570、TPS54331、TPS562201、
TPS562208 和 LT8610。系统用本地多语言向量、BM25 和固定术语扩展检索；
聊天模型生成结构化 AnswerDraft，逐事实审核后再渲染。引用、页码、版本
和链接由程序填充，模型不会直接生成。

`STATUS` 含义：

* `ANSWERED` — 至少一条事实通过审核并直接回答了用户问题。
* `PARTIAL_ANSWER` — 已回答部分内容，但还有未覆盖的范围。
* `NEEDS_CLARIFICATION` — 需要补全型号或主题；页面显示追问与选项按钮。
* `INSUFFICIENT_EVIDENCE` — 本次资料不足，已具体说明缺什么。
* `SOURCE_CONFLICT` — 资料中存在冲突条件，未做单边结论。
* `MODEL_ERROR` / `RETRIEVAL_ERROR` — 本地服务异常；技术细节在 message 中。
* `OUT_OF_SCOPE` — 超出当前文档问答范围。

文档问答不构成正式工程合格判定。绝对最大额定值、典型值与推荐工作值
必须在工程判定层处理，而不是聊天模型自行承诺。

## 验收矩阵

```powershell
.\.venv\python.exe .\scripts\acceptance_matrix.py
```

输出位于 `reports/mvp/answer_fix/acceptance_matrix.json`，覆盖 14 个真实
问题（含英文与中英混合、澄清追问与无证据问题）。每一题都会记录
`answer_text`、`citations`、`claim_count` 与延迟。
