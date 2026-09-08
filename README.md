# LocalChipAdvisor Hybrid Search MVP

一个最小芯片检索演示：结构化字段判断硬约束，文档检索寻找解释证据，DeepSeek 只解析自然语言或依据已检索证据组织回答。

## 架构

```text
自然语言 -> 本地正则路由 -> DeepSeek Parser（仅必要时）
-> SQLite 硬约束过滤 -> FTS5 + 可选本地 Ollama 向量
-> RRF -> Top 6 Evidence -> DeepSeek 有证据回答 -> Python 引用校验
```

| 任务 | 决策来源 | 模型边界 |
|---|---|---|
| Vin/Vout/Iout、布尔功能、封装 | SQLite | 模型不能决定是否满足 |
| 型号、OCP、EN/UVLO 等精确词 | FTS5 | 只找证据 |
| 口语、改写、跨语言解释问题 | 本地 embedding | 只找证据 |
| 技术说明 | DeepSeek + 最多 6 条证据 | 不得补写事实或引用 |

`UNKNOWN` 永远不能当成 `PASS`。没有证据时不调用 DeepSeek。文件、页码和 section 由 Python 绑定，模型只能使用本次提供的 `[E1]` 等编号。

## 快速开始

要求 Python 3.11。DeepSeek 用于 Chat/Parser；Ollama 只需 `qwen3-embedding:0.6b`。

```powershell
cd D:\LocalChipAdvisor
$env:DEEPSEEK_API_KEY="your-api-key"
$env:LCA_CHAT_MODEL="deepseek-v4-flash"  # 可选
.\.venv\python.exe -m pip install -e ".[dev]"
ollama pull qwen3-embedding:0.6b
.\.venv\python.exe scripts\ingest.py --reset --embed
```

也可以在仓库根目录创建本地 `.env`，写入 `DEEPSEEK_API_KEY=你的key`；程序会自动读取。`.env` 已被 Git 忽略。不要把真实 key 写入 `.env.example` 或 Git。

当前清单是 `data\products.json`：3 颗芯片（MP4570、MPQ4570、MP023）和 4 份文档。EV4570-F-01A 是评估板资料，只作为 MP4570 的补充文档，不作为芯片候选。PDF 路径和 SHA-256 均由清单固定。

重新处理 `data\raw\mps` 中的 PDF 并建立本地向量：

```powershell
.\.venv\python.exe scripts\ingest.py --reset --embed
```

脚本不联网下载资料，不做 OCR，默认也不会计算 embedding。

## 运行与测试

```powershell
.\.venv\python.exe scripts\check.py
.\.venv\python.exe scripts\demo.py "MP4570 最大输入电压是多少？"
.\.venv\python.exe scripts\demo.py "MP4570 短路以后怎么保护？"
.\.venv\python.exe -m pytest -q -p no:cacheprovider
```

测试只用 fake/mock，不访问真实服务。`check.py` 默认不调用 DeepSeek；显式运行以下命令才产生一次很小的真实请求：

```powershell
.\.venv\python.exe scripts\check.py --deepseek-smoke
```

## 调用预算

- 普通选型：通常 1 次 Parser；无效 JSON 最多重试 1 次；默认无 answer call。
- 明确型号的精确参数问答：0 次 DeepSeek、0 次 embedding。
- 明确型号的技术问答：0 次 Parser，1 次 grounded answer。
- 明确多型号比较：0 次 DeepSeek、0 次 embedding。

## 工程边界

优先使用已审核的官方来源。RAG 只能寻找证据，不能判定硬约束；模型不能补写数据库中没有的参数。正式工程选型仍需工程师核对原始 Datasheet、适用条件和版本。
