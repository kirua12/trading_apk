from __future__ import annotations

import ctypes
import platform
import time
from ctypes import wintypes
from dataclasses import asdict, dataclass
from typing import Iterable


DEFAULT_WINDOW_KEYWORDS = (
    "공동인증서",
    "인증서",
    "전자서명",
    "비밀번호",
    "암호",
    "certificate",
    "password",
    "signkorea",
    "crosscert",
)


@dataclass(frozen=True)
class WindowInfo:
    hwnd: int
    title: str
    class_name: str
    pid: int

    def safe_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["hwnd"] = str(self.hwnd)
        return data


@dataclass(frozen=True)
class TypeResult:
    window: WindowInfo
    chars_typed: int
    pressed_enter: bool

    def safe_dict(self) -> dict[str, object]:
        return {
            "window": self.window.safe_dict(),
            "chars_typed": self.chars_typed,
            "pressed_enter": self.pressed_enter,
        }


class RemoteKeyboardError(RuntimeError):
    pass


def list_candidate_windows(
    keywords: Iterable[str] | None = None,
    *,
    include_all: bool = False,
) -> list[WindowInfo]:
    _ensure_windows()
    terms = _normalize_keywords(keywords)
    windows = _enum_windows()
    if include_all:
        return windows
    return [win for win in windows if _matches(win, terms)]


def type_password_into_candidate(
    password: str,
    *,
    keywords: Iterable[str] | None = None,
    press_enter: bool = True,
    delay_seconds: float = 0.02,
) -> TypeResult:
    _ensure_windows()
    if not password:
        raise RemoteKeyboardError("password is required")
    if len(password) > 256:
        raise RemoteKeyboardError("password is too long")

    windows = list_candidate_windows(keywords)
    if not windows:
        raise RemoteKeyboardError("certificate/password window was not found")

    target = windows[0]
    chars_typed = len(password)
    if not _focus_window(target.hwnd):
        raise RemoteKeyboardError(f"failed to focus target window: {target.title}")

    time.sleep(0.15)
    try:
        _send_unicode_text(password, delay_seconds=delay_seconds)
        if press_enter:
            _send_vk(0x0D)
    finally:
        password = ""
    return TypeResult(window=target, chars_typed=chars_typed, pressed_enter=press_enter)


def _ensure_windows() -> None:
    if platform.system().lower() != "windows":
        raise RemoteKeyboardError("remote keyboard is only available on Windows")


def _normalize_keywords(keywords: Iterable[str] | None) -> tuple[str, ...]:
    raw = tuple(keywords or DEFAULT_WINDOW_KEYWORDS)
    terms = tuple(str(item).strip().lower() for item in raw if str(item).strip())
    return terms or tuple(term.lower() for term in DEFAULT_WINDOW_KEYWORDS)


def _matches(window: WindowInfo, terms: tuple[str, ...]) -> bool:
    haystack = f"{window.title} {window.class_name}".lower()
    return any(term in haystack for term in terms)


def _enum_windows() -> list[WindowInfo]:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    result: list[WindowInfo] = []

    enum_proc_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def callback(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        title_length = user32.GetWindowTextLengthW(hwnd)
        if title_length <= 0:
            return True
        title_buffer = ctypes.create_unicode_buffer(title_length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, title_length + 1)
        title = title_buffer.value.strip()
        if not title:
            return True

        class_buffer = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, class_buffer, 256)
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        result.append(
            WindowInfo(
                hwnd=int(hwnd),
                title=title,
                class_name=class_buffer.value,
                pid=int(pid.value),
            )
        )
        return True

    if not user32.EnumWindows(enum_proc_type(callback), 0):
        raise RemoteKeyboardError("failed to enumerate windows")
    return result


def _focus_window(hwnd: int) -> bool:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    SW_RESTORE = 9
    user32.ShowWindow(hwnd, SW_RESTORE)

    current_thread = kernel32.GetCurrentThreadId()
    foreground = user32.GetForegroundWindow()
    foreground_thread = user32.GetWindowThreadProcessId(foreground, None) if foreground else 0
    target_thread = user32.GetWindowThreadProcessId(hwnd, None)
    attached_foreground = False
    attached_target = False
    try:
        if foreground_thread and foreground_thread != current_thread:
            attached_foreground = bool(user32.AttachThreadInput(current_thread, foreground_thread, True))
        if target_thread and target_thread != current_thread:
            attached_target = bool(user32.AttachThreadInput(current_thread, target_thread, True))
        user32.BringWindowToTop(hwnd)
        user32.SetFocus(hwnd)
        user32.SetForegroundWindow(hwnd)
    finally:
        if attached_target:
            user32.AttachThreadInput(current_thread, target_thread, False)
        if attached_foreground:
            user32.AttachThreadInput(current_thread, foreground_thread, False)

    user32.SetForegroundWindow(hwnd)
    return bool(user32.GetForegroundWindow() == hwnd)


ULONG_PTR = wintypes.WPARAM


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", INPUT_UNION),
    ]


def _send_unicode_text(text: str, *, delay_seconds: float) -> None:
    for char in text:
        _send_unicode_char(char)
        if delay_seconds > 0:
            time.sleep(delay_seconds)


def _send_unicode_char(char: str) -> None:
    code = ord(char)
    KEYEVENTF_KEYUP = 0x0002
    KEYEVENTF_UNICODE = 0x0004
    _send_input(KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, 0))
    _send_input(KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0))


def _send_vk(vk: int) -> None:
    KEYEVENTF_KEYUP = 0x0002
    _send_input(KEYBDINPUT(vk, 0, 0, 0, 0))
    _send_input(KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, 0))


def _send_input(keyboard_input: KEYBDINPUT) -> None:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    INPUT_KEYBOARD = 1
    item = INPUT(type=INPUT_KEYBOARD, union=INPUT_UNION(ki=keyboard_input))
    sent = user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(item))
    if sent != 1:
        raise RemoteKeyboardError("SendInput failed")
