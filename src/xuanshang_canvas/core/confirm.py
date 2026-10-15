"""规则 8：花积分的操作（以及超大图要被压缩这种需要使用者点头的事）每次都要单独确认。

三档，能用哪档用哪档：
1. AI 工具自带的确认弹窗（MCP elicitation）—— 在 MCP 服务那一层做，因为要用到会话；
2. 插件自己弹 Windows 确认窗口 —— 只有人能点，AI 点不了；
3. 两步确认码 —— 最后备用。确认码交给 AI，AI 可以不经使用者同意直接用，所以只是软限制。
"""

from __future__ import annotations

import hashlib
import json
import secrets
import sys
import threading
import time
from dataclasses import dataclass
from typing import Any

from .errors import RuleViolation

# MessageBox 的常量
_MB_YESNO = 0x00000004
_MB_ICONQUESTION = 0x00000020
_MB_DEFBUTTON2 = 0x00000100  # 默认按钮是「否」，避免误按回车就提交
_MB_SETFOREGROUND = 0x00010000
_MB_TOPMOST = 0x00040000
_IDYES, _IDNO, _TIMEOUT = 6, 7, 32000


@dataclass
class ConfirmRequest:
    """一次需要使用者确认的操作。"""

    action: str  # 如 submit_generation
    title: str  # 弹窗标题
    sheet: str  # 确认单正文，给人看的
    payload: dict[str, Any]  # 绑定确认码用的全部参数

    def signature(self) -> str:
        blob = json.dumps({"action": self.action, "payload": self.payload}, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def _desktop_visible() -> bool:
    """当前进程是否在能看见窗口的桌面上（比如不是在后台服务里跑）。"""
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        station = user32.GetProcessWindowStation()
        if not station:
            return False

        class USEROBJECTFLAGS(ctypes.Structure):
            _fields_ = [("fInherit", wintypes.BOOL), ("fReserved", wintypes.BOOL), ("dwFlags", wintypes.DWORD)]

        flags = USEROBJECTFLAGS()
        needed = wintypes.DWORD()
        ok = user32.GetUserObjectInformationW(station, 1, ctypes.byref(flags), ctypes.sizeof(flags), ctypes.byref(needed))
        return bool(ok) and bool(flags.dwFlags & 0x0001)  # WSF_VISIBLE
    except Exception:
        return False


def show_popup(title: str, text: str, timeout_seconds: float) -> str:
    """弹 Windows 确认窗口。返回 yes / no / timeout / unavailable。会阻塞，调用方放到线程里跑。"""
    if sys.platform != "win32" or not _desktop_visible():
        return "unavailable"
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        message_box = user32.MessageBoxTimeoutW
        message_box.argtypes = [wintypes.HWND, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.UINT, wintypes.WORD, wintypes.DWORD]
        message_box.restype = ctypes.c_int
    except (AttributeError, OSError):
        return "unavailable"
    flags = _MB_YESNO | _MB_ICONQUESTION | _MB_DEFBUTTON2 | _MB_SETFOREGROUND | _MB_TOPMOST
    seconds = max(5, int(timeout_seconds))
    body = f"{text}\n\n（{seconds} 秒内不点就算取消）"
    result = message_box(None, body, title, flags, 0, seconds * 1000)
    if result == _IDYES:
        return "yes"
    if result == _IDNO:
        return "no"
    if result == _TIMEOUT:
        return "timeout"
    return "unavailable"


class ConfirmCodes:
    """两步确认码：绑定这次的全部参数，参数一变就作废；有效期内只能用一次。"""

    def __init__(self, ttl_seconds: float = 300.0):
        self.ttl = ttl_seconds
        self._codes: dict[str, tuple[str, str, float]] = {}
        self._lock = threading.Lock()

    def issue(self, request: ConfirmRequest) -> str:
        code = "-".join(secrets.token_hex(2).upper() for _ in range(2))
        with self._lock:
            self._purge()
            self._codes[code] = (request.action, request.signature(), time.time() + self.ttl)
        return code

    def redeem(self, request: ConfirmRequest, code: str) -> None:
        code = (code or "").strip().upper()
        with self._lock:
            self._purge()
            entry = self._codes.pop(code, None)
        if entry is None:
            raise RuleViolation("确认码无效、已经用过或已过期（5 分钟内有效，只能用一次）。请不带确认码重新调用，拿新的确认单。")
        action, signature, _ = entry
        if action != request.action or signature != request.signature():
            raise RuleViolation("确认码和这次的参数对不上（参数或素材变了），确认码已作废。请不带确认码重新调用，拿新的确认单。")

    def _purge(self) -> None:
        now = time.time()
        for key in [key for key, (_, _, expires) in self._codes.items() if expires < now]:
            del self._codes[key]
