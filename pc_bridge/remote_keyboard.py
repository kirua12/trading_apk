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
    method: str
    attempts: tuple[str, ...] = ()

    def safe_dict(self) -> dict[str, object]:
        return {
            "window": self.window.safe_dict(),
            "child": self.child.safe_dict() if self.child else None,
            "chars_typed": self.chars_typed,
            "pressed_enter": self.pressed_enter,
            "foreground_hwnd": str(self.foreground_hwnd),
            "clicked_child": self.clicked_child,
            "method": self.method,
            "attempts": list(self.attempts),
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
    input_method: str = "auto",
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
    method, attempts = _deliver_password(
        password,
        target_hwnd=target.hwnd,
        child_hwnd=child.hwnd if child else None,
        press_enter=press_enter,
        delay_seconds=delay_seconds,
        input_method=input_method,
    )
    password = ""

    foreground_hwnd = int(_user32.GetForegroundWindow())
    return TypeResult(
        window=target,
        child=child,
        chars_typed=chars_typed,
        pressed_enter=press_enter,
        foreground_hwnd=foreground_hwnd,
        clicked_child=clicked_child,
        method=method,
        attempts=tuple(attempts),
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


def _deliver_password(
    password: str,
    *,
    target_hwnd: int,
    child_hwnd: int | None,
    press_enter: bool,
    delay_seconds: float,
    input_method: str,
) -> tuple[str, list[str]]:
    attempts: list[str] = []
    methods = _method_sequence(input_method, child_hwnd)
    for method in methods:
        try:
            if method == "paste":
                _paste_text(password, press_enter=press_enter)
            elif method == "vk":
                _send_vk_text(password, delay_seconds=delay_seconds)
                if press_enter:
                    _send_vk(0x0D)
            elif method == "message":
                _post_char_text(child_hwnd or target_hwnd, password, press_enter=press_enter)
            elif method == "settext":
                if not child_hwnd:
                    raise RemoteKeyboardError("no child input control was found")
                _set_window_text(child_hwnd, password)
                if press_enter:
                    _send_vk(0x0D)
            elif method == "unicode":
                _send_unicode_text(password, delay_seconds=delay_seconds)
                if press_enter:
                    _send_vk(0x0D)
            else:
                raise RemoteKeyboardError(f"unknown input method: {method}")
            attempts.append(f"{method}: sent")
            return method, attempts
        except RemoteKeyboardError as exc:
            attempts.append(f"{method}: {exc}")
    raise RemoteKeyboardError("; ".join(attempts) or "all input methods failed")


def _method_sequence(input_method: str, child_hwnd: int | None) -> tuple[str, ...]:
    method = (input_method or "auto").strip().lower().replace("-", "_")
    aliases = {
        "keyboard": "vk",
        "key": "vk",
        "keys": "vk",
        "sendinput": "unicode",
        "sendinput_unicode": "unicode",
        "clipboard": "paste",
        "wm_char": "message",
        "direct": "settext",
    }
    method = aliases.get(method, method)
    if method == "auto":
        # Unicode SendInput can report success while secure controls ignore it,
        # so auto starts with methods that often work with certificate dialogs.
        return ("paste", "vk", "message", "settext", "unicode") if child_hwnd else ("paste", "vk", "unicode")
    if method not in {"paste", "vk", "message", "settext", "unicode"}:
        raise RemoteKeyboardError(f"unknown input method: {input_method}")
    return (method,)


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
    _send_vk_down(vk)
    _send_vk_up(vk)


def _send_vk_down(vk: int) -> None:
    _send_input(KEYBDINPUT(vk, 0, 0, 0, 0))


def _send_vk_up(vk: int) -> None:
    _send_input(KEYBDINPUT(vk, 0, KEYEVENTF_KEYUP, 0, 0))


def _send_vk_text(text: str, *, delay_seconds: float) -> None:
    for char in text:
        scan = _user32.VkKeyScanW(char)
        if scan == -1:
            raise RemoteKeyboardError(f"cannot map character to keyboard: {char!r}")
        vk = scan & 0xFF
        shift_state = (scan >> 8) & 0xFF
        modifiers: list[int] = []
        if shift_state & 0x01:
            modifiers.append(VK_SHIFT)
        if shift_state & 0x02:
            modifiers.append(VK_CONTROL)
        if shift_state & 0x04:
            modifiers.append(VK_MENU)
        for modifier in modifiers:
            _send_vk_down(modifier)
        _send_vk(vk)
        for modifier in reversed(modifiers):
            _send_vk_up(modifier)
        if delay_seconds > 0:
            time.sleep(delay_seconds)


def _paste_text(text: str, *, press_enter: bool) -> None:
    previous = _get_clipboard_text()
    _set_clipboard_text(text)
    try:
        time.sleep(0.08)
        _send_ctrl_v()
        time.sleep(0.2)
        if press_enter:
            _send_vk(0x0D)
    finally:
        if previous is None:
            _empty_clipboard()
        else:
            _set_clipboard_text(previous)


def _send_ctrl_v() -> None:
    _send_vk_down(VK_CONTROL)
    try:
        _send_vk(ord("V"))
    finally:
        _send_vk_up(VK_CONTROL)


def _post_char_text(hwnd: int, text: str, *, press_enter: bool) -> None:
    for char in text:
        if not _user32.PostMessageW(hwnd, WM_CHAR, ord(char), 0):
            raise RemoteKeyboardError("PostMessageW WM_CHAR failed")
        time.sleep(0.01)
    if press_enter and not _user32.PostMessageW(hwnd, WM_CHAR, 0x0D, 0):
        raise RemoteKeyboardError("PostMessageW ENTER failed")


def _set_window_text(hwnd: int, text: str) -> None:
    if not _user32.SetWindowTextW(hwnd, text):
        error = ctypes.get_last_error()
        raise RemoteKeyboardError(f"SetWindowTextW failed: {error}")


def _get_clipboard_text() -> str | None:
    if not _user32.OpenClipboard(None):
        raise RemoteKeyboardError("OpenClipboard failed")
    try:
        handle = _user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        locked = _kernel32.GlobalLock(handle)
        if not locked:
            return None
        try:
            return ctypes.wstring_at(locked)
        finally:
            _kernel32.GlobalUnlock(handle)
    finally:
        _user32.CloseClipboard()


def _set_clipboard_text(text: str) -> None:
    raw = (text + "\0").encode("utf-16-le")
    handle = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(raw))
    if not handle:
        raise RemoteKeyboardError("GlobalAlloc failed")
    locked = _kernel32.GlobalLock(handle)
    if not locked:
        raise RemoteKeyboardError("GlobalLock failed")
    try:
        ctypes.memmove(locked, raw, len(raw))
    finally:
        _kernel32.GlobalUnlock(handle)

    if not _user32.OpenClipboard(None):
        raise RemoteKeyboardError("OpenClipboard failed")
    try:
        if not _user32.EmptyClipboard():
            raise RemoteKeyboardError("EmptyClipboard failed")
        if not _user32.SetClipboardData(CF_UNICODETEXT, handle):
            raise RemoteKeyboardError("SetClipboardData failed")
        handle = None
    finally:
        _user32.CloseClipboard()


def _empty_clipboard() -> None:
    if not _user32.OpenClipboard(None):
        return
    try:
        _user32.EmptyClipboard()
    finally:
        _user32.CloseClipboard()


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
CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
WM_CHAR = 0x0102


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
    _user32.VkKeyScanW.argtypes = [wintypes.WCHAR]
    _user32.VkKeyScanW.restype = ctypes.c_short
    _user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.PostMessageW.restype = wintypes.BOOL
    _user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
    _user32.SetWindowTextW.restype = wintypes.BOOL
    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.CloseClipboard.argtypes = []
    _user32.CloseClipboard.restype = wintypes.BOOL
    _user32.EmptyClipboard.argtypes = []
    _user32.EmptyClipboard.restype = wintypes.BOOL
    _user32.GetClipboardData.argtypes = [wintypes.UINT]
    _user32.GetClipboardData.restype = wintypes.HANDLE
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.SetClipboardData.restype = wintypes.HANDLE
    _user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    _user32.SendInput.restype = wintypes.UINT

    _kernel32.GetCurrentThreadId.argtypes = []
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD
    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    _kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalLock.restype = ctypes.c_void_p
    _kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalUnlock.restype = wintypes.BOOL
    _winapi_configured = True
