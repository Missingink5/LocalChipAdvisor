# LocalChipAdvisor MVP 运行手册

## 启动

双击项目根目录的 `启动MVP.cmd`。脚本会启动本地 Ollama，并在
`http://127.0.0.1:8501` 打开 Streamlit 页面。首次聊天模型加载可能需要数秒。

PowerShell 启动方式：

```powershell
Set-Location D:\LocalChipAdvisor
.\scripts\start_mvp.ps1
```

CLI 问答：

```powershell
.\.venv\python.exe .\scripts\ask_mvp.py --query "MP4570 太热会自己停吗？"
```

仅查看检索结果时添加 `--retrieval-only`。该模式不代表证据已经足够回答。

## 能力与边界

当前语料为四份已审核 datasheet，支持 MP4570、TPS54331、TPS562201、
TPS562208 和 LT8610。系统用本地多语言向量、BM25 和固定术语扩展检索；
聊天模型只选择本次实际召回的证据，引用、页码、版本和链接由程序填充。

默认展示 datasheet 原文。过温和 MP4570 60V 边界有程序控制的中文事实模板；
其他问题可能只显示英文原文。参数提取只保留明确原句及位置，不自动补全条件。
系统不执行完整正式选型，也不保证硬件安全或全工况适用性。

若显示 `RETRIEVAL_ERROR`，先运行：

```powershell
.\scripts\start_ollama.ps1
.\.venv\python.exe .\scripts\build_mvp.py
```

最终索引清单为 `data\mvp\demo-v2\manifest.json`。
