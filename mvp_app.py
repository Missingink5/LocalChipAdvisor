"""Local Streamlit UI for the conversational, evidence-bound advisor.

The page is a chat-style surface. The browser session owns its own
ConversationState in st.session_state; the shared AdvisorService is cached
via @st.cache_resource but never stores per-user state.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import streamlit as st

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "src"))

from local_chip_advisor.mvp.contracts import (
    Citation, ClarificationRequest, UserTurn, gen_id,
)
from local_chip_advisor.mvp.conversation import new_session_state
from local_chip_advisor.mvp.service import AdvisorService


STATUS_LABELS = {
    "ANSWERED": "已找到支持回答的证据",
    "PARTIAL_ANSWER": "部分回答（部分证据不足以完整回答）",
    "NEEDS_CLARIFICATION": "需要澄清",
    "INSUFFICIENT_EVIDENCE": "证据不足",
    "SOURCE_CONFLICT": "资料存在冲突",
    "MODEL_ERROR": "本地模型出错",
    "RETRIEVAL_ERROR": "检索未就绪或失败",
    "OUT_OF_SCOPE": "超出当前文档问答范围",
}

EXAMPLES = [
    "MP4570 的过温关断保护在多少度触发、多少度恢复？",
    "MP4570 太烫了会自己停下来吗？凉到多少度会自己再开？",
    "MP4570 软启动时间怎么设置？",
    "MP4570 轻载时频率会变化吗？",
    "TPS54331 软启动是否可编程？",
    "TPS562201 欠压保护阈值是多少？",
]


@st.cache_resource
def service(manifest: str):
    return AdvisorService(Path(manifest))


@st.cache_data
def corpus_documents():
    return json.loads((ROOT / "evaluations/corpus_manifest.json").read_text("utf-8"))["documents"]


def _init_session_state() -> None:
    if "session_id" not in st.session_state:
        st.session_state["session_id"] = gen_id("ui")
    if "conversation_state" not in st.session_state:
        st.session_state["conversation_state"] = new_session_state(
            st.session_state["session_id"],
        )
    if "messages" not in st.session_state:
        st.session_state["messages"] = []  # list of {role, content, ...}
    if "pending_event_id" not in st.session_state:
        st.session_state["pending_event_id"] = None


def _format_citation(citation: Citation, index: int) -> str:
    products = "、".join(citation.products) if citation.products else "未提供"
    return (f"来源 {citation.marker} · {products} · "
            f"版本 {citation.revision or '未提供'} · "
            f"物理页 {citation.page_start}–{citation.page_end}")


def _render_clarification(clarification: ClarificationRequest) -> None:
    st.info(clarification.question)
    cols = st.columns(min(3, max(1, len(clarification.options))))
    for column, option in zip(cols, clarification.options):
        if column.button(option.label, key=f"opt-{clarification.request_id}-{option.option_id}",
                         use_container_width=True):
            _handle_user_action(option.label, selected_option_id=option.option_id,
                                clarification_request_id=clarification.request_id)


def _render_result(result: dict) -> None:
    status = result.get("status", "UNKNOWN")
    label = STATUS_LABELS.get(status, status)
    if status in {"ANSWERED", "PARTIAL_ANSWER"}:
        st.success(label)
    elif status in {"MODEL_ERROR", "RETRIEVAL_ERROR"}:
        st.error(label)
    else:
        st.info(label)

    answer_text = result.get("answer_text") or result.get("message", "")
    if answer_text:
        st.markdown(answer_text)

    for limitation in result.get("limitations", []):
        st.caption(f"限制：{limitation}")

    citations = result.get("citations", []) or []
    if citations:
        st.markdown("**来源**")
        for i, citation_dict in enumerate(citations):
            try:
                citation = Citation.model_validate(citation_dict)
            except Exception:
                st.caption(citation_dict.get("marker", str(i)))
                continue
            with st.expander(_format_citation(citation, i)):
                _render_source_detail(citation)

    if result.get("clarification"):
        try:
            clarification = ClarificationRequest.model_validate(result["clarification"])
        except Exception:
            clarification = None
        if clarification is not None:
            _render_clarification(clarification)


def _render_source_detail(citation: Citation) -> None:
    record = None
    try:
        index = service("").index
        record = index.by_id.get(citation.chunk_id)
    except Exception:
        record = None
    if record is not None:
        st.text(str(record.get("text", "")))
    url = citation.source_url or ""
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
                        mime="application/pdf",
                        key=f"pdf-{citation.chunk_id}",
                    )
            break


def _handle_user_action(text: str, *, selected_option_id: str | None = None,
                        clarification_request_id: str | None = None) -> None:
    event_id = gen_id("ev")
    if st.session_state.get("pending_event_id"):
        return  # another event is in flight; ignore double submit
    st.session_state["pending_event_id"] = event_id
    st.session_state["messages"].append({"role": "user", "content": text,
                                          "selected_option_id": selected_option_id,
                                          "event_id": event_id})

    state = st.session_state["conversation_state"]
    manifest = st.session_state.get("manifest_input") or str(
        ROOT / "data/mvp/demo-v2/manifest.json")
    svc = service(manifest)
    user_turn = UserTurn(turn_id=event_id, text=text)
    with st.spinner("正在本地检索并核验证据，首次加载可能较慢…"):
        state, full = svc.handle_turn(
            state, user_turn,
            selected_option_id=selected_option_id,
        )
    st.session_state["conversation_state"] = state
    st.session_state["messages"].append({"role": "assistant",
                                          "content": full.model_dump(),
                                          "event_id": event_id})
    st.session_state["pending_event_id"] = None


def _new_session() -> None:
    st.session_state["session_id"] = gen_id("ui")
    st.session_state["conversation_state"] = new_session_state(
        st.session_state["session_id"])
    st.session_state["messages"] = []
    st.session_state["pending_event_id"] = None


def main():
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--manifest", default=str(ROOT / "data/mvp/demo-v2/manifest.json"))
    args, _ = parser.parse_known_args()
    st.set_page_config(page_title="芯片资料助手", page_icon="🔎", layout="wide")
    st.title("芯片资料助手 · 本地 MVP")
    st.caption("MP4570 · TPS54331 · TPS562201 · TPS562208 · LT8610")
    st.write("输入中文、英文或混合问题，查看简短中文回答与证据来源。"
             "工程适用性需另行核验。")
    _init_session_state()

    with st.sidebar:
        manifest = st.text_input("索引 manifest", args.manifest, key="manifest_input")
        debug = st.checkbox("展开调试面板", value=False, key="debug_mode")
        if st.button("新对话", use_container_width=True):
            _new_session()
            st.rerun()
        st.caption("每个浏览器会话独立；不共享模型客户端以外的任何状态。")

    cols = st.columns(3)
    for column, example in zip(cols, EXAMPLES):
        if column.button(example, key=f"example-{example[:10]}", use_container_width=True):
            _handle_user_action(example)
            st.rerun()

    for message in st.session_state["messages"]:
        if message["role"] == "user":
            with st.chat_message("user"):
                st.write(message["content"])
        else:
            with st.chat_message("assistant"):
                _render_result(message["content"])

    user_text = st.chat_input("输入问题，例如：MP4570 太热会自己停吗？")
    if user_text and user_text.strip():
        _handle_user_action(user_text.strip())
        st.rerun()

    if st.session_state.get("debug_mode"):
        with st.expander("会话状态", expanded=False):
            st.json(st.session_state["conversation_state"].model_dump())


if __name__ == "__main__":
    main()
