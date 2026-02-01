"""
与协议无关的 OpenCode 控制逻辑，供 Telegram 与 Matrix 共用。
"""
from __future__ import annotations

import os

import opencode_client as opencode
import opencode_runner as runner

MAX_MESSAGE_LENGTH = 4096
current_session_id: str | None = None


async def get_or_create_session() -> str:
    global current_session_id
    if current_session_id:
        return current_session_id
    sessions = await opencode.list_sessions()
    if not sessions:
        session = await opencode.create_session()
        current_session_id = session["id"]
    else:
        current_session_id = sessions[0]["id"]
    return current_session_id


def switch_session(session_id: str) -> None:
    global current_session_id
    current_session_id = session_id


def chunk_text(text: str, size: int = MAX_MESSAGE_LENGTH) -> list[str]:
    if len(text) <= size:
        return [text] if text else []
    out = []
    for i in range(0, len(text), size):
        out.append(text[i : i + size])
    return out


async def get_sessions() -> list[dict]:
    return await opencode.list_sessions()


def handle_start() -> str:
    return (
        "直接发消息即会转发给 OpenCode 执行，仅回复最终结果。"
        " /session 查看会话并可点击按钮切换，/new 新建会话，/opencode 查看并启动 OpenCode。"
    )


async def handle_session_list() -> str:
    try:
        sessions = await opencode.list_sessions()
    except Exception as e:
        return f"获取会话失败: {e}"
    if not sessions:
        return "当前无会话，发送任意消息将自动创建。"
    lines = []
    for s in sessions:
        sid = s.get("id", "")
        title = s.get("title") or "(无标题)"
        mark = " [当前]" if sid == current_session_id else ""
        lines.append(f"• {sid[:8]}… {title}{mark}")
    return "会话列表（点击下方按钮切换当前会话）:\n" + "\n".join(lines)


async def handle_new_session() -> str:
    global current_session_id
    try:
        session = await opencode.create_session()
        current_session_id = session["id"]
        return "已切换到新会话。"
    except Exception as e:
        return f"创建会话失败: {e}"


def handle_opencode_status() -> str:
    base = runner.get_base_url()
    port = runner._parse_port_from_base_url(base)
    if port in (80, 443):
        port = runner.DEFAULT_PORT
    in_use, pid, cmd = runner.check_port(port)
    healthy = runner.is_opencode_healthy()
    lines = [
        f"端口: {port}",
        f"占用: {'是' if in_use else '否'}",
        f"健康: {'是' if healthy else '否'}",
    ]
    if pid:
        lines.append(f"进程: pid={pid}")
    if cmd:
        lines.append(f"命令: {cmd}")
    return "OpenCode 状态:\n" + "\n".join(lines)


def is_opencode_healthy() -> bool:
    return runner.is_opencode_healthy()


def handle_start_opencode(log_path: str) -> tuple[bool, str]:
    return runner.ensure_opencode_running(log_path=log_path)


async def handle_switch_session(session_id: str) -> str:
    try:
        sessions = await opencode.list_sessions()
        title = "(无标题)"
        for s in sessions:
            if s.get("id") == session_id:
                title = s.get("title") or title
                break
        switch_session(session_id)
        return f"已切换到会话: {title}"
    except Exception as e:
        return f"切换失败: {e}"


async def handle_message(text: str) -> str:
    try:
        session_id = await get_or_create_session()
        result = await opencode.send_message(session_id, text)
    except Exception as e:
        return f"调用 OpenCode 失败: {e}"
    if not result:
        return "(无文本结果)"
    return result
