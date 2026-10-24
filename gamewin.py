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


def controller_prompt_matches(image, template):
    """확인한 연결 해제 문구·오류 코드의 밝은 글자 모양을 비교한다."""
    from PIL import ImageChops, ImageFilter
    crop = image.resize((960, 540)).crop((350, 215, 610, 290)).convert("L")
    actual = crop.point(lambda v: 255 if v > 160 else 0)
    expected = template.crop((0, 0, 260, 75)).convert("L").point(lambda v: 255 if v > 160 else 0)
    na, ne = actual.histogram()[255], expected.histogram()[255]
    if not na or not ne:
        return False
    # 캡처 축소·JPEG의 글자 경계 오차 1픽셀만 허용하고 양쪽 글자 모양을 확인한다.
    covered = ImageChops.multiply(expected, actual.filter(ImageFilter.MaxFilter(3))).histogram()[255] / ne
    precise = ImageChops.multiply(actual, expected.filter(ImageFilter.MaxFilter(3))).histogram()[255] / na
    # shortcut: 한국어·현재 UI 크기의 확인 창, 언어나 UI 배율 변경 시 템플릿 갱신.
    # 10-24: 실제 창이 0.81~0.86으로 나와 0.90 기준에서 놓침. 창이 아닌 화면 18장은 최대 covered 0.70·precise 0.41.
    return covered > 0.75 and precise > 0.75


def dismiss_controller_prompt(pad):
    """가상 패드 재연결 후, 알려진 연결 해제 창만 확인하고 닫는다."""
    from pathlib import Path
    from PIL import Image, ImageGrab
    import screen
    pid = _game_pid()
    hwnd = screen.game_hwnd(pid) if pid else None
    if not hwnd:
        return
    if u32.GetForegroundWindow() != hwnd:
        return
    with Image.open(Path(__file__).with_name("controller_disconnected.png")) as template:
        for _ in range(12):
            if u32.GetForegroundWindow() != hwnd:
                return
            x, y, w, h = screen.client_rect(hwnd)
            if w <= 0 or h <= 0:
                return
            image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            matches = controller_prompt_matches(image, template)
            if matches:
                if pad:
                    time.sleep(2.5)  # 게임이 새 가상 패드를 인식한 뒤에 확인 입력.
                if u32.GetForegroundWindow() != hwnd:
                    raise RuntimeError("연결 해제 창 확인 전 게임 포커스가 바뀌었어")
                image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
                if not controller_prompt_matches(image, template):
                    return
                if pad:
                    pad.tap("A")
                    time.sleep(0.6)
                if u32.GetForegroundWindow() != hwnd:
                    raise RuntimeError("연결 해제 창 확인 중 게임 포커스가 바뀌었어")
                image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
                if controller_prompt_matches(image, template):
                    # 새 패드의 A를 받지 않는 경우에도 같은 확인 버튼만 마우스로 누른다.
                    screen.click(x + w / 2, y + h * (328 / 540))
                    time.sleep(1.2)
                    if u32.GetForegroundWindow() != hwnd:
                        raise RuntimeError("연결 해제 창 확인 중 게임 포커스가 바뀌었어")
                    image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
                    if controller_prompt_matches(image, template):
                        u32.keybd_event(0x20, u32.MapVirtualKeyW(0x20, 0), 0, 0)
                        time.sleep(0.08)
                        u32.keybd_event(0x20, u32.MapVirtualKeyW(0x20, 0), 2, 0)
                        time.sleep(1.2)
                        if u32.GetForegroundWindow() != hwnd:
                            raise RuntimeError("연결 해제 창 확인 중 게임 포커스가 바뀌었어")
                        image = ImageGrab.grab(bbox=(x, y, x + w, y + h))
                        if controller_prompt_matches(image, template):
                            raise RuntimeError("컨트롤러 연결 해제 창을 닫지 못했어")
                print("컨트롤러 연결 해제 창 확인 후 닫았어.", flush=True)
                return
            time.sleep(0.25)
