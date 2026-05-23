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

PASSWORD_CHILD_KEYWORDS = (
    "비밀번호",
    "암호",
    "password",
    "passwd",
    "pwd",
)

INPUT_CLASS_KEYWORDS = (
    "edit",
    "richedit",
    "password",
    "text",
    "afx",
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
class ChildInfo:
    hwnd: int
    title: str
    class_name: str
    visible: bool
    enabled: bool

    def safe_dict(self) -> dict[str, object]:
        data = asdict(self)
        data["hwnd"] = str(self.hwnd)
        return data


@dataclass(frozen=True)
class TypeResult:
    window: WindowInfo
    child: ChildInfo | None
    chars_typed: int
    pressed_enter: bool
    foreground_hwnd: int
    clicked_child: bool
    method: str = "sendinput_unicode"

    def safe_dict(self) -> dict[str, object]:
        return {
            "window": self.window.safe_dict(),
            "child": self.child.safe_dict() if self.child else None,
            "chars_typed": self.chars_typed,
            "pressed_enter": self.pressed_enter,
            "foreground_hwnd": str(self.foreground_hwnd),
            "clicked_child": self.clicked_child,
            "method": self.method,
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
    target_hwnd: int | None = None,
    press_enter: bool = True,
    delay_seconds: float = 0.02,
) -> TypeResult:
    _ensure_windows()
    if not password:
        raise RemoteKeyboardError("password is required")
    if len(password) > 256:
        raise RemoteKeyboardError("password is too long")

    target = _resolve_target_window(keywords, target_hwnd)
    child = _find_input_child(target.hwnd)
    focus_ok = _focus_window(target.hwnd, child.hwnd if child else None)
    if not focus_ok:
        raise RemoteKeyboardError(f"failed to focus target window: {target.title}")

    clicked_child = False
    if child:
        clicked_child = _click_hwnd_center(child.hwnd)

    chars_typed = len(password)
    time.sleep(0.15)
    try:
        _send_unicode_text(password, delay_seconds=delay_seconds)
        if press_enter:
            _send_vk(0x0D)
    finally:
        password = ""

    foreground_hwnd = int(_user32.GetForegroundWindow())
    return TypeResult(
        window=target,
        child=child,
        chars_typed=chars_typed,
        pressed_enter=press_enter,
        foreground_hwnd=foreground_hwnd,
        clicked_child=clicked_child,
    )


def _ensure_windows() -> None:
    if platform.system().lower() != "windows":
        raise RemoteKeyboardError("remote keyboard is only available on Windows")
    _configure_winapi()


def _normalize_keywords(keywords: Iterable[str] | None) -> tuple[str, ...]:
    raw = tuple(keywords or DEFAULT_WINDOW_KEYWORDS)
    terms = tuple(str(item).strip().lower() for item in raw if str(item).strip())
    return terms or tuple(term.lower() for term in DEFAULT_WINDOW_KEYWORDS)


def _matches(window: WindowInfo, terms: tuple[str, ...]) -> bool:
    haystack = f"{window.title} {window.class_name}".lower()
    return any(term in haystack for term in terms)


def _resolve_target_window(
    keywords: Iterable[str] | None,
    target_hwnd: int | None,
) -> WindowInfo:
    if target_hwnd:
        for window in list_candidate_windows(include_all=True):
            if window.hwnd == int(target_hwnd):
                return window
        raise RemoteKeyboardError(f"target window was not found: {target_hwnd}")

    windows = list_candidate_windows(keywords)
    if not windows:
        raise RemoteKeyboardError("certificate/password window was not found")
    return windows[0]


def _enum_windows() -> list[WindowInfo]:
    result: list[WindowInfo] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        if not _user32.IsWindowVisible(hwnd):
            return True
        title = _get_window_text(hwnd)
        if not title:
            return True
        pid = wintypes.DWORD()
        _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        result.append(
            WindowInfo(
                hwnd=int(hwnd),
                title=title,
                class_name=_get_class_name(hwnd),
                pid=int(pid.value),
            )
        )
        return True

    if not _user32.EnumWindows(WNDENUMPROC(callback), 0):
        error = ctypes.get_last_error()
        detail = f" WinError={error}" if error else ""
        raise RemoteKeyboardError(
            "failed to enumerate windows; run the bridge in the same visible "
            f"Windows desktop session as the certificate window.{detail}"
        )
    return result


def _enum_child_windows(parent_hwnd: int) -> list[ChildInfo]:
    result: list[ChildInfo] = []

    def callback(hwnd: int, _lparam: int) -> bool:
        result.append(
            ChildInfo(
                hwnd=int(hwnd),
                title=_get_window_text(hwnd),
                class_name=_get_class_name(hwnd),
                visible=bool(_user32.IsWindowVisible(hwnd)),
                enabled=bool(_user32.IsWindowEnabled(hwnd)),
            )
        )
        return True

    _user32.EnumChildWindows(parent_hwnd, WNDENUMPROC(callback), 0)
    return result


def _find_input_child(parent_hwnd: int) -> ChildInfo | None:
    children = [
        child
        for child in _enum_child_windows(parent_hwnd)
        if child.visible and child.enabled
    ]
    if not children:
        return None

    for child in children:
        haystack = f"{child.title} {child.class_name}".lower()
        if any(term.lower() in haystack for term in PASSWORD_CHILD_KEYWORDS):
            return child

    for child in children:
        class_name = child.class_name.lower()
        if any(term in class_name for term in INPUT_CLASS_KEYWORDS):
            return child

    return None


def _get_window_text(hwnd: int) -> str:
    length = _user32.GetWindowTextLengthW(hwnd)
    if length <= 0:
        return ""
    buffer = ctypes.create_unicode_buffer(length + 1)
    _user32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value.strip()


def _get_class_name(hwnd: int) -> str:
    buffer = ctypes.create_unicode_buffer(256)
    _user32.GetClassNameW(hwnd, buffer, 256)
    return buffer.value.strip()


def _focus_window(parent_hwnd: int, child_hwnd: int | None = None) -> bool:
    SW_RESTORE = 9
    parent = wintypes.HWND(parent_hwnd)
    child = wintypes.HWND(child_hwnd) if child_hwnd else parent

    _user32.ShowWindow(parent, SW_RESTORE)
    current_thread = _kernel32.GetCurrentThreadId()
    foreground = _user32.GetForegroundWindow()
    foreground_thread = _thread_id(foreground) if foreground else 0
    target_thread = _thread_id(parent)

    attached_foreground = False
    attached_target = False
    try:
        if foreground_thread and foreground_thread != current_thread:
            attached_foreground = bool(
                _user32.AttachThreadInput(current_thread, foreground_thread, True)
            )
        if target_thread and target_thread != current_thread:
            attached_target = bool(
                _user32.AttachThreadInput(current_thread, target_thread, True)
            )

        _user32.BringWindowToTop(parent)
        _user32.SetForegroundWindow(parent)
        _user32.SetActiveWindow(parent)
        _user32.SetFocus(child)
    finally:
        if attached_target:
            _user32.AttachThreadInput(current_thread, target_thread, False)
        if attached_foreground:
            _user32.AttachThreadInput(current_thread, foreground_thread, False)

    time.sleep(0.05)
    _user32.SetForegroundWindow(parent)
    foreground_after = _user32.GetForegroundWindow()
    return bool(int(foreground_after) == int(parent_hwnd))


def _thread_id(hwnd: int) -> int:
    if not hwnd:
        return 0
    return int(_user32.GetWindowThreadProcessId(hwnd, None))


def _click_hwnd_center(hwnd: int) -> bool:
    rect = RECT()
    if not _user32.GetWindowRect(hwnd, ctypes.byref(rect)):
        return False
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return False
    x = rect.left + width // 2
    y = rect.top + height // 2
    if not _user32.SetCursorPos(x, y):
        return False
    time.sleep(0.03)
    _send_mouse_click()
    return True


def _send_unicode_text(text: str, *, delay_seconds: float) -> None:
    for char in text:
        _send_unicode_char(char)
        if delay_seconds > 0:
            time.sleep(delay_seconds)


def _send_unicode_char(char: str) -> None:
    code = ord(char)
    _send_input(KEYBDINPUT(0, code, KEYEVENTF_UNICODE, 0, 0))
    _send_input(KEYBDINPUT(0, code, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, 0, 0))


def _send_vk(vk: int) -> None:
    _send_input(KEYBDINPUT(vk, 0, 0, 0, 0))
    _send_input(KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, 0))


def _send_mouse_click() -> None:
    _send_input(MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0), input_type=INPUT_MOUSE)
    _send_input(MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0), input_type=INPUT_MOUSE)


def _send_input(raw_input: KEYBDINPUT | MOUSEINPUT, *, input_type: int = 1) -> None:
    if isinstance(raw_input, KEYBDINPUT):
        item = INPUT(type=input_type, union=INPUT_UNION(ki=raw_input))
    else:
        item = INPUT(type=input_type, union=INPUT_UNION(mi=raw_input))
    sent = _user32.SendInput(1, ctypes.byref(item), ctypes.sizeof(item))
    if sent != 1:
        error = ctypes.get_last_error()
        raise RemoteKeyboardError(f"SendInput failed: {error}")


_user32 = ctypes.WinDLL("user32", use_last_error=True) if platform.system().lower() == "windows" else None
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True) if platform.system().lower() == "windows" else None
_winapi_configured = False

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ULONG_PTR),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("ki", KEYBDINPUT),
        ("mi", MOUSEINPUT),
    ]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", INPUT_UNION),
    ]


def _configure_winapi() -> None:
    global _winapi_configured
    if _winapi_configured:
        return
    if _user32 is None or _kernel32 is None:
        raise RemoteKeyboardError("remote keyboard is only available on Windows")

    _user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    _user32.EnumWindows.restype = wintypes.BOOL
    _user32.EnumChildWindows.argtypes = [wintypes.HWND, WNDENUMPROC, wintypes.LPARAM]
    _user32.EnumChildWindows.restype = wintypes.BOOL
    _user32.IsWindowVisible.argtypes = [wintypes.HWND]
    _user32.IsWindowVisible.restype = wintypes.BOOL
    _user32.IsWindowEnabled.argtypes = [wintypes.HWND]
    _user32.IsWindowEnabled.restype = wintypes.BOOL
    _user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    _user32.GetWindowTextLengthW.restype = ctypes.c_int
    _user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetWindowTextW.restype = ctypes.c_int
    _user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    _user32.GetClassNameW.restype = ctypes.c_int
    _user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _user32.GetForegroundWindow.argtypes = []
    _user32.GetForegroundWindow.restype = wintypes.HWND
    _user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.ShowWindow.restype = wintypes.BOOL
    _user32.AttachThreadInput.argtypes = [wintypes.DWORD, wintypes.DWORD, wintypes.BOOL]
    _user32.AttachThreadInput.restype = wintypes.BOOL
    _user32.BringWindowToTop.argtypes = [wintypes.HWND]
    _user32.BringWindowToTop.restype = wintypes.BOOL
    _user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    _user32.SetForegroundWindow.restype = wintypes.BOOL
    _user32.SetActiveWindow.argtypes = [wintypes.HWND]
    _user32.SetActiveWindow.restype = wintypes.HWND
    _user32.SetFocus.argtypes = [wintypes.HWND]
    _user32.SetFocus.restype = wintypes.HWND
    _user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
    _user32.GetWindowRect.restype = wintypes.BOOL
    _user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
    _user32.SetCursorPos.restype = wintypes.BOOL
    _user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    _user32.SendInput.restype = wintypes.UINT

    _kernel32.GetCurrentThreadId.argtypes = []
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    _winapi_configured = True
