"""使用已登录的本机 Codex App Server 调用 Pages，不经过模型。"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from pathlib import Path


class PageTransportError(RuntimeError):
    pass


def _codex_command() -> list[str]:
    executable = shutil.which("codex.exe" if os.name == "nt" else "codex")
    if not executable and os.name == "nt":
        # npm 的 cmd 启动器会再启动 node 和 codex。直接启动包中的程序才能可靠取消。
        shim = shutil.which("codex.cmd")
        if shim:
            vendor = Path(shim).parent / "node_modules" / "@openai" / "codex" / "node_modules" / "@openai"
            executable = next((str(p) for p in vendor.glob("codex-win32-*/vendor/*/bin/codex.exe")), None)
    if not executable:
        raise PageTransportError("未找到 Codex 命令。请安装并登录 Codex CLI，再重新打开词流。")
    return [executable, "app-server", "--listen", "stdio://"]


class PageTransport:
    """一个后台任务独占一个临时会话，连接结束时释放其进程与管道。"""

    def __init__(self, cancelled: Callable[[], bool] | None = None, *, timeout: float = 45):
        self.cancelled = cancelled
        self.timeout = timeout
        self._proc: subprocess.Popen | None = None
        self._messages: queue.Queue = queue.Queue()
        self._reader: threading.Thread | None = None
        self._next_id = 0
        self._thread_id = ""

    def __enter__(self) -> PageTransport:
        self._check_cancelled()
        cwd = tempfile.gettempdir()
        try:
            self._proc = subprocess.Popen(
                _codex_command(), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, text=True, encoding="utf-8",
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), cwd=cwd,
            )
        except OSError as exc:
            raise PageTransportError("无法启动本机 Codex，请检查安装和执行权限。") from exc
        try:
            self._reader = threading.Thread(target=self._read_stdout, args=(self._proc.stdout,), daemon=True)
            self._reader.start()
            self._request("initialize", {
                "clientInfo": {"name": "wordflow", "version": "1.0"},
                "capabilities": {"experimentalApi": True},
            })
            self._send({"method": "initialized"})
            started = self._request("thread/start", {
                "ephemeral": True, "cwd": cwd, "sandbox": "read-only", "approvalPolicy": "on-request",
            })
            self._thread_id = started.get("thread", {}).get("id")
            if not self._thread_id:
                raise PageTransportError("Codex 未返回会话标识，请检查 Codex 版本。")
            return self
        except BaseException:
            self.close()
            raise

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self):
        if self._proc is None:
            return
        proc = self._proc
        try:
            if proc.stdin:
                proc.stdin.close()
        except OSError:
            pass  # 子进程可能已经断开。
        try:
            proc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        if self._reader:
            self._reader.join(timeout=1)
        self._proc = None
        self._thread_id = ""

    def _check_cancelled(self):
        if self.cancelled and self.cancelled():
            raise PageTransportError("Page 同步已取消。")

    def _read_stdout(self, stdout):
        try:
            with stdout:
                for line in stdout:
                    packet = json.loads(line)
                    if not isinstance(packet, dict):
                        break
                    if "id" in packet:
                        self._messages.put(packet)
        except (ValueError, OSError):
            pass
        finally:
            self._messages.put(None)

    def _send(self, packet: dict):
        try:
            self._proc.stdin.write(json.dumps(packet, ensure_ascii=False) + "\n")
            self._proc.stdin.flush()
        except (ValueError, OSError) as exc:
            raise PageTransportError("Codex 连接已中断。") from exc

    def _request(self, method: str, params: dict) -> dict:
        self._check_cancelled()
        self._next_id += 1
        self._send({"id": self._next_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout
        while True:
            self._check_cancelled()
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise PageTransportError("等待 Codex 或 Pages 超时，请检查网络和 Codex 登录状态。")
            try:
                packet = self._messages.get(timeout=min(0.2, remaining))
            except queue.Empty:
                continue
            if packet is None:
                raise PageTransportError("Codex 已断开或返回了无效的数据。")
            if "method" in packet:
                # 登录、额外授权等服务器请求都需用户决定；无交互的同步任务不能代批。
                self._send({"id": packet["id"], "error": {
                    "code": -32000, "message": "Interactive approval required",
                }})
                raise PageTransportError("Pages 要求额外授权。请在 Codex 中检查 Pages 连接和操作权限。")
            if packet.get("id") != self._next_id:
                continue
            if "error" in packet:
                raise PageTransportError("Codex 调用失败，请检查账号登录状态、Pages 连接和 Codex 版本。")
            if not isinstance(packet.get("result"), dict):
                raise PageTransportError("Codex 返回了无效的响应。")
            return packet["result"]

    def call(self, tool: str, arguments: dict) -> dict:
        if tool not in {"chatgpt_space.read_page", "chatgpt_space.edit_page"}:
            raise PageTransportError("词流仅支持读取或编辑学习 Page。")
        if not self._thread_id:
            raise PageTransportError("Codex 会话尚未连接。")
        result = self._request("mcpServer/tool/call", {
            "threadId": self._thread_id, "server": "codex_apps", "tool": tool, "arguments": arguments,
        })
        payload = result.get("structuredContent")
        if isinstance(payload, dict) and (not result.get("isError") or isinstance(payload.get("error"), dict)):
            return payload
        raise PageTransportError("Pages 没有返回有效结果，请检查账号和页面访问权限。")
