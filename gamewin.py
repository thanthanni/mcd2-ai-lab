"""게임 창을 자동으로 앞으로 가져오기, 진짜 패드 연결 확인(윈도우 전용)."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import time

u32 = ctypes.WinDLL("user32", use_last_error=True)
k32 = ctypes.WinDLL("kernel32", use_last_error=True)


def _game_pid():
    import subprocess
    out = subprocess.run(["tasklist", "/fi", "imagename eq Dungeons-Win64-Shipping.exe", "/fo", "csv", "/nh"],
                         capture_output=True, text=True, errors="ignore").stdout
    for line in out.splitlines():
        parts = [x.strip('"') for x in line.split('","')]
        if len(parts) > 1 and parts[1].isdigit():
            return int(parts[1])
    return None


def focus_game(pid=None) -> bool:
    """마던2 창을 맨 앞으로. 성공하면 True."""
    pid = pid or _game_pid()
    if not pid:
        return False
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, _):
        p = wt.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u32.IsWindowVisible(h):
            found.append(h)
        return True

    u32.EnumWindows(cb, 0)
    if not found:
        return False
    h = found[0]
    if u32.IsIconic(h):
        u32.ShowWindow(h, 9)                 # SW_RESTORE
    u32.keybd_event(0x12, 0, 0, 0)           # Alt를 눌렀다 떼면 윈도우가 창 전환을 허락함
    u32.keybd_event(0x12, 0, 2, 0)
    u32.SetForegroundWindow(h)
    time.sleep(0.5)
    return u32.GetForegroundWindow() == h


class _XS(ctypes.Structure):
    _fields_ = [("packet", wt.DWORD), ("buttons", wt.WORD), ("lt", ctypes.c_ubyte), ("rt", ctypes.c_ubyte),
                ("lx", ctypes.c_short), ("ly", ctypes.c_short), ("rx", ctypes.c_short), ("ry", ctypes.c_short)]


def pads_connected() -> int:
    """지금 연결된 엑스박스 패드 수(가상 패드 만들기 전에 부르면 진짜 패드 수)."""
    try:
        x = ctypes.WinDLL("xinput1_4")
    except OSError:
        return 0
    s = _XS()
    return sum(1 for i in range(4) if x.XInputGetState(i, ctypes.byref(s)) == 0)


def prepare(wait_unplug=60) -> None:
    """진짜 패드가 있으면 뺄 때까지 기다리고, 게임 창을 앞으로 가져온다."""
    if pads_connected():
        print("진짜 패드가 연결돼 있어. 빼거나 꺼 줘(엑박 버튼 길게). 빼면 바로 시작해.", flush=True)
        t = time.time()
        while pads_connected() and time.time() - t < wait_unplug:
            time.sleep(0.5)
    try:
        ok = focus_game()
    except Exception:
        ok = False
    print("게임 창을 앞으로 가져왔어." if ok else "게임 창을 못 가져왔어. 게임 창을 직접 클릭해 줘(3초).", flush=True)
    time.sleep(1 if ok else 3)
