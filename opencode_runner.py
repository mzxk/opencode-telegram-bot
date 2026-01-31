"""
检查 OpenCode 进程与端口占用，并支持启动 opencode serve。
"""
from __future__ import annotations

import os
import socket
import subprocess
import time
from typing import Optional

import httpx

DEFAULT_PORT = 4096
DEFAULT_HOST = "127.0.0.1"
OPENCODE_SERVE_CMD = ["opencode", "serve"]


def get_base_url() -> str:
    return os.environ.get("OPENCODE_BASE_URL", f"http://{DEFAULT_HOST}:{DEFAULT_PORT}")


def _parse_port_from_base_url(url: str) -> int:
    try:
        if url.startswith("http://"):
            rest = url[7:]
        elif url.startswith("https://"):
            rest = url[8:]
        else:
            rest = url
        host_port = rest.split("/")[0]
        if ":" in host_port:
            return int(host_port.split(":")[-1])
        return 80 if "https" in url else 80
    except Exception:
        return DEFAULT_PORT


def check_port(port: int) -> tuple[bool, Optional[int], Optional[str]]:
    """
    检查端口是否被占用。返回 (是否占用, pid 或 None, 进程简述或 None)。
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            s.connect((DEFAULT_HOST, port))
    except (socket.error, OSError):
        return False, None, None
    pid, cmd = _get_process_on_port(port)
    return True, pid, cmd


def _get_process_on_port(port: int) -> tuple[Optional[int], Optional[str]]:
    """Linux: 用 lsof 或 ss 获取占用端口的进程 pid 与简要命令。"""
    pid = None
    for prog in (["lsof", "-i", f":{port}", "-t"], ["fuser", f"{port}/tcp"]):
        try:
            out = subprocess.run(prog, capture_output=True, text=True, timeout=2)
            if out.returncode == 0 and (out.stdout or out.stderr or "").strip():
                raw = (out.stdout or out.stderr).strip().split()
                if raw:
                    pid = int(raw[0])
                    break
        except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
            continue
    if pid is None:
        try:
            out = subprocess.run(
                ["ss", "-tlnp"], capture_output=True, text=True, timeout=2
            )
            if out.returncode == 0:
                import re
                for line in out.stdout.splitlines():
                    if f":{port}" in line and "pid=" in line:
                        m = re.search(r"pid=(\d+)", line)
                        if m:
                            pid = int(m.group(1))
                            break
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    cmd = None
    if pid:
        try:
            with open(f"/proc/{pid}/cmdline") as f:
                cmd = f.read().replace("\0", " ").strip()[:80]
        except Exception:
            pass
    return pid, cmd


def is_opencode_healthy() -> bool:
    """请求 /global/health，判断 OpenCode 是否可用。"""
    base = get_base_url()
    auth = None
    if os.environ.get("OPENCODE_SERVER_PASSWORD"):
        auth = (
            os.environ.get("OPENCODE_SERVER_USERNAME", "opencode"),
            os.environ.get("OPENCODE_SERVER_PASSWORD"),
        )
    try:
        r = httpx.get(f"{base.rstrip('/')}/global/health", auth=auth, timeout=3)
        if r.status_code == 200:
            data = r.json()
            return data.get("healthy") is True
    except Exception:
        pass
    return False


def start_opencode(
    port: Optional[int] = None,
    hostname: Optional[str] = None,
    log_path: Optional[str] = None,
) -> tuple[bool, str]:
    """
    后台启动 opencode serve。返回 (是否成功, 说明信息)。
    """
    port = port or _parse_port_from_base_url(get_base_url())
    if port == 80:
        port = DEFAULT_PORT
    hostname = hostname or DEFAULT_HOST
    args = list(OPENCODE_SERVE_CMD) + ["--port", str(port), "--hostname", hostname]
    env = os.environ.copy()
    try:
        out = open(log_path, "a") if log_path else subprocess.DEVNULL
        err = out if log_path else subprocess.DEVNULL
        p = subprocess.Popen(
            args,
            stdout=out,
            stderr=err,
            env=env,
            start_new_session=True,
            cwd=os.path.expanduser("~"),
        )
    except FileNotFoundError:
        return False, "未找到 opencode 命令，请确认已安装并在 PATH 中"
    except Exception as e:
        return False, str(e)
    if log_path and out != subprocess.DEVNULL:
        try:
            out.close()
        except Exception:
            pass
    return True, f"已启动 opencode serve (pid={p.pid}, {hostname}:{port})"


def ensure_opencode_running(
    port: Optional[int] = None,
    log_path: Optional[str] = None,
) -> tuple[bool, str]:
    """
    若 OpenCode 未健康则尝试启动。返回 (是否可用, 说明)。
    """
    if is_opencode_healthy():
        return True, "OpenCode 已在运行"
    port = port or _parse_port_from_base_url(get_base_url())
    if port == 80:
        port = DEFAULT_PORT
    in_use, pid, cmd = check_port(port)
    if in_use and not is_opencode_healthy():
        return False, f"端口 {port} 已被占用 (pid={pid}, {cmd or '?'})，但非 OpenCode"
    if in_use:
        return True, "OpenCode 已在运行"
    ok, msg = start_opencode(port=port, log_path=log_path)
    if not ok:
        return False, msg
    for _ in range(10):
        time.sleep(1)
        if is_opencode_healthy():
            return True, msg
    return False, "已启动但健康检查未通过，请稍后重试"
