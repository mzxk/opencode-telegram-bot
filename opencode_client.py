"""
OpenCode HTTP 客户端：健康检查、会话列表/创建、发消息。
解析 POST /session/:id/message 响应时只提取最终结果（最后一条 text part）。
"""
from __future__ import annotations

import os
from typing import Optional, Tuple

import httpx

DEFAULT_BASE_URL = "http://127.0.0.1:4096"
MESSAGE_TIMEOUT = 300.0


def _auth() -> Optional[Tuple[str, str]]:
    password = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    if not password:
        return None
    user = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
    return (user, password)


def _get_base_url() -> str:
    return os.environ.get("OPENCODE_BASE_URL", DEFAULT_BASE_URL)


def _extract_final_result(data: dict) -> str:
    """从 POST /session/:id/message 的响应中只取最终结果（最后一个 text part）。"""
    parts = data.get("parts") or []
    text_parts = [p.get("text") for p in parts if p.get("type") == "text" and "text" in p]
    if not text_parts:
        return ""
    return text_parts[-1].strip()


async def health() -> dict:
    """GET /global/health"""
    async with httpx.AsyncClient(
        base_url=_get_base_url(), auth=_auth(), timeout=10.0
    ) as client:
        r = await client.get("/global/health")
        r.raise_for_status()
        return r.json()


async def list_sessions() -> list:
    """GET /session"""
    async with httpx.AsyncClient(
        base_url=_get_base_url(), auth=_auth(), timeout=10.0
    ) as client:
        r = await client.get("/session")
        r.raise_for_status()
        return r.json()


async def create_session(title: Optional[str] = None) -> dict:
    """POST /session"""
    async with httpx.AsyncClient(
        base_url=_get_base_url(), auth=_auth(), timeout=10.0
    ) as client:
        r = await client.post("/session", json={"title": title} if title else {})
        r.raise_for_status()
        return r.json()


async def send_message(session_id: str, text: str) -> str:
    """
    POST /session/:id/message，只返回解析出的最终结果（最后一条 text part）。
    """
    async with httpx.AsyncClient(
        base_url=_get_base_url(), auth=_auth(), timeout=MESSAGE_TIMEOUT
    ) as client:
        r = await client.post(
            f"/session/{session_id}/message",
            json={"parts": [{"type": "text", "text": text}]},
        )
        r.raise_for_status()
        data = r.json()
        return _extract_final_result(data)
