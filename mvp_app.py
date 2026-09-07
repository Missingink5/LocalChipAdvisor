"""Local Streamlit presentation; all inference goes through AdvisorService."""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))
STATUS = {
    "ANSWERED": "已找到支持回答的证据",
    "NEEDS_CLARIFICATION": "需要澄清",
    "INSUFFICIENT_EVIDENCE": "证据不足",
    "SOURCE_CONFLICT": "资料存在冲突",
    "MODEL_ERROR": "本地模型出错",
    "RETRIEVAL_ERROR": "检索未就绪或失败",
    "OUT_OF_SCOPE": "超出当前文档问答范围",
    "RETRIEVED": "已检索原文（未运行回答核验）",
}
EXAMPLES = {
    "正式中文": "MP4570 的过温关断保护在多少度触发、多少度恢复？",
    "中文口语": "MP4570 太烫了会自己停下来吗？凉到多少度会自己再开？",
    "English": "At what temperatures does the MP4570 thermal shutdown trigger and recover?",
    "中英混合": "MP4570 的 thermal shutdown 是多少度触发、多少度恢复？",
}


@st.cache_resource
def service(manifest: str):
    from local_chip_advisor.mvp.service import AdvisorService

    return AdvisorService(Path(manifest))


@st.cache_data
def corpus_documents():
    return json.loads((ROOT / "evaluations/corpus_manifest.json").read_text("utf-8"))["documents"]


def show_source(item: dict, index: int):
    st.caption(
        f"型号：{', '.join(item.get('products', []))} · "
        f"版本：{item.get('revision', '未提供')} · "
        f"物理页：{item.get('page_start', '?')}–{item.get('page_end', '?')}"
    )
    st.text(str(item.get("text", "")))
    url = str(item.get("source_url", ""))
    if urlparse(url).scheme in {"https", "http"}:
        st.link_button("打开官方来源", url)
    # Download only manifest-listed PDFs whose bytes still match the registered hash.
    for doc in corpus_documents():
        if url and doc["source_url"] == url:
            pdf = (ROOT / doc["local_file"]).resolve()
            if pdf.is_relative_to(ROOT / "data/raw") and pdf.is_file():
                data = pdf.read_bytes()
                if hashlib.sha256(data).hexdigest().lower() == doc["sha256"].lower():
                    st.download_button(
                        "下载此原始 PDF", data, file_name=pdf.name,
                        mime="application/pdf", key=f"pdf-{index}",
                    )
            break


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--manifest", default=str(ROOT / "data/mvp/demo-v2/manifest.json"))
    args, _ = parser.parse_known_args()
    st.set_page_config(page_title="芯片资料助手", page_icon="🔎", layout="wide")
    st.title("芯片资料助手 · 本地 MVP")
    st.caption("MP4570 · TPS54331 · TPS562201 · TPS562208 · LT8610")
    st.write("输入中文、英文或混合问题，查看原文证据与来源。工程适用性需另行核验。")
    with st.sidebar:
        manifest = st.text_input("索引 manifest", args.manifest)
        retrieval_only = st.checkbox("仅检索原文（跳过回答模型）")
        debug = st.checkbox("展开检索和耗时")
        st.caption("推理在本机 Ollama 执行。此页为单轮问答，不继承上一轮型号。")
    for column, (label, query) in zip(st.columns(4), EXAMPLES.items()):
        if column.button(label, use_container_width=True):
            st.session_state["query"] = query
    with st.form("ask"):
        query = st.text_area("问题", key="query", placeholder="MP4570 太热了会自己停吗？")
        submit = st.form_submit_button("查询", type="primary")
    if submit:
        if not query.strip():
            st.warning("请输入问题。")
        else:
            try:
                with st.spinner("正在本地检索并核验证据，首次加载可能较慢…"):
                    result = service(manifest).ask(query, retrieval_only=retrieval_only)
                st.session_state["result"] = result
                st.session_state["result_query"] = query
            except Exception as exc:  # noqa: BLE001 - UI boundary reports initialization failures.
                st.session_state["result"] = {
                    "status": "RETRIEVAL_ERROR", "message": f"本地服务无法启动：{exc}",
                }
                st.session_state["result_query"] = query
    result = st.session_state.get("result")
    if not result:
        return
    st.caption(f"本次问题：{st.session_state.get('result_query', '')}")
    status = result.get("status", "UNKNOWN")
    label = STATUS.get(status, status)
    if status == "ANSWERED":
        st.success(label)
    elif status in {"MODEL_ERROR", "RETRIEVAL_ERROR"}:
        st.error(label)
    else:
        st.info(label)
    st.write(result.get("message", ""))
    for fact in result.get("rendered_facts", []):
        st.write(fact)
    if result.get("engineering_result"):
        st.caption(result["engineering_result"])
    if result.get("parameters"):
        st.write("**提取条件（待确认）与原句出处**")
        st.json(result["parameters"])
    for quote in result.get("quotes", []):
        st.text(quote.get("text", ""))
        st.caption(f"证据：{quote.get('chunk_id', '')}")
    for i, item in enumerate(result.get("evidence", [])):
        with st.expander(f"来源 {i + 1} · {item.get('chunk_id', '')}"):
            show_source(item, i)
    st.caption(f"知识库构建：{result.get('build_id', '未加载')}")
    for limitation in result.get("limitations", []):
        st.caption(f"限制：{limitation}")
    if debug:
        with st.expander("本次检索原始结果与耗时", expanded=True):
            st.json(result)


if __name__ == "__main__":
    main()
