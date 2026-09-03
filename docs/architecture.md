# 首版技术架构决策

核验日期：2026-09-03

## 1. 核心原则

- 结构化参数与确定性规则负责合规判断。
- RAG 负责找回原文证据和生成可读解释。
- 引用由程序绑定证据对象，LLM 不生成来源。
- 草稿数据和已发布数据物理/逻辑隔离。
- 单用户、localhost、可断网、可回滚。

## 2. 首测技术栈

| 层 | 选择 | 原因 |
|---|---|---|
| Python | 独立 Conda prefix，Python 3.11 | 避开系统 Python 3.13 的生态兼容风险 |
| 本地模型运行器 | Ollama for Windows | 原生支持 RTX 4060，提供本地 Chat/Embed API |
| 生成模型候选 | `qwen3.5:9b-q4_K_M` | 官方包约 6.6 GB；先实测显存、速度和中文技术解释 |
| Embedding 候选 | `qwen3-embedding:0.6b` | 官方包约 639 MB；适合 16 GB RAM 的基线 |
| 产品主数据 | SQLite | 结构化字段、审核状态、版本和证据关系可事务化管理 |
| 文档向量索引 | Chroma `PersistentClient` | 单机本地持久化，首版操作简单 |
| 精确检索 | SQLite/FTS 与 BM25 | 支持料号、术语、数值和关键词召回 |
| 文档解析 | PyMuPDF 基线 + 表格/复杂页回退管线 | 保留页码；复杂表格必须人工核验 |
| API | FastAPI + Uvicorn | 核心服务与界面解耦，只绑定 `127.0.0.1` |
| UI | Streamlit | 快速提供需求确认、矩阵、证据查看和评测入口 |
| 测试 | pytest | 固化三态规则、排序、证据与回归测试 |

Reranker 不进入第一个可运行切片。先测混合检索 Recall@10；若未达 95%，再加入轻量本地 Reranker 并重新测量内存、延迟和召回。

## 3. 资源策略

- `OLLAMA_MAX_LOADED_MODELS=1`。
- `OLLAMA_NUM_PARALLEL=1`。
- 生成模型首测上下文为 4096 tokens；通过显存与延迟测试后再评估 8192。
- 摄取阶段可批量加载 Embedding 模型；交互阶段按需切换模型。
- 不以模型标称 256K 上下文作为本机运行目标。
- Ollama 模型目录设置为 `D:\LocalChipAdvisor\models\ollama`。

## 4. 数据流

```text
MPS 官方文件/页面
  -> 下载清单、哈希、版本、来源 URL
  -> 页级文本/表格解析和证据片段
  -> 自动抽取到草稿产品记录
  -> 人工核对关键字段与证据
  -> 发布到版本化 SQLite 产品库
  -> 构建 FTS/BM25 与 Chroma 证据索引

用户自然语言
  -> 需求字段抽取与单位归一化
  -> 歧义/缺失检查
  -> 用户确认需求卡
  -> SQLite 硬过滤与基础计算
  -> PASS / FAIL / UNKNOWN 矩阵
  -> 合格、近似、待核实三个候选区
  -> 混合检索候选型号的官方证据
  -> 程序绑定证据 ID
  -> 本地 LLM 生成中文解释
  -> 程序渲染可点击/可定位出处
```

## 5. 网络边界

- 开发期联网下载软件、模型和公开 MPS 资料。
- 运行期 API 与 UI 只监听 `127.0.0.1`。
- 不配置任何云模型/API key。
- 发布验收时阻断 Ollama、Python 和应用进程的公网访问，并真实断网测试。
- Windows 版 Ollama 可能自动检查更新；封闭运行阶段由出站规则阻断。

## 6. 当前官方依据

- Ollama Windows 文档：https://docs.ollama.com/windows
- Ollama GPU 支持：https://docs.ollama.com/gpu
- Ollama FAQ 与资源配置：https://docs.ollama.com/faq
- Qwen3.5 官方 Ollama 标签：https://ollama.com/library/qwen3.5/tags
- Qwen3 Embedding 官方 Ollama标签：https://ollama.com/library/qwen3-embedding/tags
- Chroma 本地客户端：https://docs.trychroma.com/docs/run-chroma/clients
- Chroma 开源与遥测说明：https://docs.trychroma.com/docs/overview/oss

依赖安装后生成精确版本快照。任何升级先在新环境和相同评测集上验证，不直接覆盖已通过版本。
