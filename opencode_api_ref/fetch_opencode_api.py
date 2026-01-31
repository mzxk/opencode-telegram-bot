"""
根据 opencode.md 用 curl 请求 OpenCode 各接口，将 curl 命令与响应保存到 opencode_api_ref/。
需本地 opencode serve 已启动（默认 http://127.0.0.1:4096）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

BASE = os.environ.get("OPENCODE_BASE_URL", "http://127.0.0.1:4096")
AUTH = os.environ.get("OPENCODE_SERVER_PASSWORD")
OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "opencode_api_ref")
TIMEOUT_SSE = 2
TIMEOUT_NORMAL = 10

# (method, path, 需要 :id 的 session?, 需要 :messageID?, query 示例, body 示例)
ENDPOINTS = [
    ("GET", "/global/health", False, False, None, None),
    ("GET", "/global/event", False, False, None, None),  # SSE
    ("GET", "/project", False, False, None, None),
    ("GET", "/project/current", False, False, None, None),
    ("GET", "/path", False, False, None, None),
    ("GET", "/vcs", False, False, None, None),
    ("POST", "/instance/dispose", False, False, None, None),
    ("GET", "/config", False, False, None, None),
    ("PATCH", "/config", False, False, None, "{}"),
    ("GET", "/config/providers", False, False, None, None),
    ("GET", "/provider", False, False, None, None),
    ("GET", "/provider/auth", False, False, None, None),
    ("GET", "/session", False, False, None, None),
    ("POST", "/session", False, False, None, "{}"),
    ("GET", "/session/status", False, False, None, None),
    ("GET", "/session/:id", True, False, None, None),
    ("DELETE", "/session/:id", True, False, None, None),
    ("PATCH", "/session/:id", True, False, None, '{"title":"test"}'),
    ("GET", "/session/:id/children", True, False, None, None),
    ("GET", "/session/:id/todo", True, False, None, None),
    ("POST", "/session/:id/init", True, False, None, '{"providerID":"","modelID":""}'),
    ("POST", "/session/:id/fork", True, False, None, "{}"),
    ("POST", "/session/:id/abort", True, False, None, None),
    ("POST", "/session/:id/share", True, False, None, None),
    ("DELETE", "/session/:id/share", True, False, None, None),
    ("GET", "/session/:id/diff", True, False, None, None),
    ("POST", "/session/:id/summarize", True, False, None, '{"providerID":"","modelID":""}'),
    ("POST", "/session/:id/revert", True, False, None, '{"messageID":""}'),
    ("POST", "/session/:id/unrevert", True, False, None, None),
    ("GET", "/session/:id/message", True, False, "limit=5", None),
    ("POST", "/session/:id/message", True, False, None, '{"parts":[{"type":"text","text":"hi"}]}'),
    ("GET", "/session/:id/message/:messageID", True, True, None, None),
    ("POST", "/session/:id/prompt_async", True, False, None, '{"parts":[{"type":"text","text":"hi"}]}'),
    ("POST", "/session/:id/command", True, False, None, '{"command":"/help","arguments":[]}'),
    ("POST", "/session/:id/shell", True, False, None, '{"agent":"build","command":"echo ok"}'),
    ("GET", "/command", False, False, None, None),
    ("GET", "/find", False, False, "pattern=test", None),
    ("GET", "/find/file", False, False, "query=bot", None),
    ("GET", "/find/symbol", False, False, "query=main", None),
    ("GET", "/file", False, False, "path=.", None),
    ("GET", "/file/content", False, False, "path=.", None),
    ("GET", "/file/status", False, False, None, None),
    ("GET", "/experimental/tool/ids", False, False, None, None),
    ("GET", "/experimental/tool", False, False, "provider=vllm&model=QWEN", None),
    ("GET", "/lsp", False, False, None, None),
    ("GET", "/formatter", False, False, None, None),
    ("GET", "/mcp", False, False, None, None),
    ("POST", "/mcp", False, False, None, '{"name":"test","config":{}}'),
    ("GET", "/agent", False, False, None, None),
    ("POST", "/log", False, False, None, '{"service":"test","level":"info","message":"test"}'),
    ("POST", "/tui/append-prompt", False, False, None, '{"body":""}'),
    ("POST", "/tui/open-help", False, False, None, None),
    ("POST", "/tui/open-sessions", False, False, None, None),
    ("POST", "/tui/open-themes", False, False, None, None),
    ("POST", "/tui/open-models", False, False, None, None),
    ("POST", "/tui/submit-prompt", False, False, None, None),
    ("POST", "/tui/clear-prompt", False, False, None, None),
    ("POST", "/tui/execute-command", False, False, None, '{"command":"/help"}'),
    ("POST", "/tui/show-toast", False, False, None, '{"title":"","message":""}'),
    ("GET", "/tui/control/next", False, False, None, None),  # 可能阻塞
    ("POST", "/tui/control/response", False, False, None, '{"body":{}}'),
    ("GET", "/event", False, False, None, None),  # SSE
]


def safe_name(method: str, path: str, query: str | None, idx: int) -> str:
    p = path.strip("/")
    p = p.replace("/", "_")
    p = re.sub(r":\w+", "X", p)
    if query:
        p += "_q"
    return f"{method}_{p}_{idx}"


def run_curl(method: str, url: str, body: str | None, timeout: int) -> tuple[str, int, str]:
    cmd = ["curl", "-s", "-w", "\n%{http_code}", "-X", method, "--max-time", str(timeout)]
    if AUTH:
        cmd.extend(["-u", f"opencode:{AUTH}"])
    if body:
        cmd.extend(["-H", "Content-Type: application/json", "-d", body])
    cmd.append(url)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 2)
        stdout = (out.stdout or "").strip()
        stderr = out.stderr or ""
        if "\n" in stdout:
            body_out, code = stdout.rsplit("\n", 1)
            try:
                code = int(code)
            except ValueError:
                code = 0
        else:
            body_out = stdout
            code = 0
        return body_out, code, stderr
    except subprocess.TimeoutExpired:
        return "(timeout)", 0, ""
    except Exception as e:
        return "", 0, str(e)


def get_session_id() -> str | None:
    url = f"{BASE.rstrip('/')}/session"
    cmd = ["curl", "-s", "-X", "GET", "--max-time", str(TIMEOUT_NORMAL)]
    if AUTH:
        cmd.extend(["-u", f"opencode:{AUTH}"])
    cmd.append(url)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_NORMAL + 2)
        data = json.loads(out.stdout or "[]")
        if isinstance(data, list) and data and isinstance(data[0], dict) and "id" in data[0]:
            return data[0]["id"]
    except Exception:
        pass
    return None


def get_message_id(session_id: str) -> str | None:
    url = f"{BASE.rstrip('/')}/session/{session_id}/message?limit=3"
    cmd = ["curl", "-s", "-X", "GET", "--max-time", str(TIMEOUT_NORMAL)]
    if AUTH:
        cmd.extend(["-u", f"opencode:{AUTH}"])
    cmd.append(url)
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=TIMEOUT_NORMAL + 2)
        data = json.loads(out.stdout or "[]")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            info = data[0].get("info") or data[0]
            if isinstance(info, dict) and "id" in info:
                return info["id"]
    except Exception:
        pass
    return None


def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)
    session_id = get_session_id()
    message_id = get_message_id(session_id) if session_id else None
    index = []
    for idx, (method, path_orig, need_sid, need_mid, query, body) in enumerate(ENDPOINTS):
        path = path_orig.replace(":id", session_id or ":id").replace(":messageID", message_id or ":messageID")
        url = f"{BASE.rstrip('/')}{path}"
        if query:
            url += "?" + query
        timeout = TIMEOUT_SSE if "/event" in path_orig or "control/next" in path_orig else TIMEOUT_NORMAL
        body_out, code, stderr = run_curl(method, url, body, timeout)
        name = safe_name(method, path_orig.split("?")[0], query, idx)
        curl_cmd = f"curl -s -X {method}"
        if AUTH:
            curl_cmd += f" -u opencode:$OPENCODE_SERVER_PASSWORD"
        if body:
            curl_cmd += f" -H 'Content-Type: application/json' -d '{body}'"
        curl_cmd += f" --max-time {timeout} '{url}'"
        curl_path = os.path.join(OUT_DIR, f"{name}.curl.txt")
        with open(curl_path, "w", encoding="utf-8") as f:
            f.write(curl_cmd)
        resp_path = os.path.join(OUT_DIR, f"{name}.json")
        try:
            if body_out and body_out != "(timeout)" and (body_out.startswith("{") or body_out.startswith("[")):
                json.loads(body_out)
            with open(resp_path, "w", encoding="utf-8") as f:
                f.write(body_out if body_out else "(empty)")
        except (json.JSONDecodeError, TypeError):
            with open(resp_path, "w", encoding="utf-8") as f:
                f.write(body_out if body_out else "(empty)")
        index.append((method, path_orig, name, code))
    index_path = os.path.join(OUT_DIR, "index.txt")
    with open(index_path, "w", encoding="utf-8") as f:
        f.write("method\tpath\tname\thttp_code\n")
        for method, path, name, code in index:
            f.write(f"{method}\t{path}\t{name}\t{code}\n")
    print(f"session_id={session_id}, message_id={message_id}")
    print(f"wrote {len(ENDPOINTS)} entries to {OUT_DIR}")
    for method, path, name, code in index:
        print(f"  {method} {path} -> {name}.json ({code})")


if __name__ == "__main__":
    main()
