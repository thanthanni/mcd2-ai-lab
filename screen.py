"""세계 좌표 → 화면 좌표(마우스 클릭 이동용). 카메라는 PlayerCameraManager.CameraCachePrivate.POV에서 읽는다."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import math
import struct
import time

u32 = ctypes.WinDLL("user32", use_last_error=True)
try:
    u32.SetProcessDPIAware()
except Exception:
    pass


class Camera:
    def __init__(self, ue):
        self.ue = ue
        self.mgr = None
        self.pov_off = None
        self.f = {}

    def find(self):
        ue = self.ue
        for name in ("DungeonsPlayerCameraManager", "PlayerCameraManager"):
            for o in ue.find_instances(name):
                if not ue.objname(o).startswith("Default__"):
                    self.mgr = o
                    break
            if self.mgr:
                break
        if not self.mgr:
            raise RuntimeError("카메라를 못 찾았어")
        cache = ue.field(self.mgr, "CameraCachePrivate")
        entry = ue.props(cache.struct)
        pov = entry["POV"]
        self.pov_off = cache.offset + pov.offset
        view = ue.props(pov.struct)
        for k in ("Location", "Rotation", "FOV", "OrthoWidth", "ProjectionMode", "AspectRatio"):
            if k in view:
                self.f[k] = view[k].offset
        return self

    def read(self):
        ue, a = self.ue, self.mgr + self.pov_off
        loc = struct.unpack("<ddd", ue.read(a + self.f["Location"], 24))
        pitch, yaw, roll = struct.unpack("<ddd", ue.read(a + self.f["Rotation"], 24))
        fov = ue.f32(a + self.f["FOV"])
        mode = ue.u8(a + self.f["ProjectionMode"]) if "ProjectionMode" in self.f else 0
        ortho = ue.f32(a + self.f["OrthoWidth"]) if "OrthoWidth" in self.f else 0
        return {"loc": loc, "pitch": pitch, "yaw": yaw, "roll": roll, "fov": fov, "mode": mode, "ortho": ortho}


def client_rect(hwnd):
    r = wt.RECT()
    u32.GetClientRect(hwnd, ctypes.byref(r))
    p = wt.POINT(0, 0)
    u32.ClientToScreen(hwnd, ctypes.byref(p))
    return p.x, p.y, r.right, r.bottom


def project(cam, p, rect):
    """세계 점 p → 화면 (x, y). 카메라 뒤면 None."""
    ox, oy, w, h = rect
    pr, yr = math.radians(cam["pitch"]), math.radians(cam["yaw"])
    fwd = (math.cos(pr) * math.cos(yr), math.cos(pr) * math.sin(yr), math.sin(pr))
    right = (-math.sin(yr), math.cos(yr), 0.0)
    up = (-math.sin(pr) * math.cos(yr), -math.sin(pr) * math.sin(yr), math.cos(pr))
    d = [p[i] - cam["loc"][i] for i in range(3)]
    cx = sum(d[i] * right[i] for i in range(3))
    cy = sum(d[i] * up[i] for i in range(3))
    cz = sum(d[i] * fwd[i] for i in range(3))
    if cam["mode"] == 1:                      # 직교 투영
        scale = w / cam["ortho"]
        return ox + w / 2 + cx * scale, oy + h / 2 - cy * scale
    if cz <= 1:
        return None
    f = (w / 2) / math.tan(math.radians(cam["fov"]) / 2)
    return ox + w / 2 + cx / cz * f, oy + h / 2 - cy / cz * f


MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x2, 0x4
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x8, 0x10


def click(x, y, hold=0.05, right=False):
    u32.SetCursorPos(int(x), int(y))
    time.sleep(0.02)
    u32.mouse_event(MOUSEEVENTF_RIGHTDOWN if right else MOUSEEVENTF_LEFTDOWN, 0, 0, 0, 0)
    time.sleep(hold)
    u32.mouse_event(MOUSEEVENTF_RIGHTUP if right else MOUSEEVENTF_LEFTUP, 0, 0, 0, 0)


def game_hwnd(pid):
    found = []

    @ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)
    def cb(h, _):
        p = wt.DWORD()
        u32.GetWindowThreadProcessId(h, ctypes.byref(p))
        if p.value == pid and u32.IsWindowVisible(h):
            found.append(h)
        return True

    u32.EnumWindows(cb, 0)
    return found[0] if found else None


class Clicker:
    """세계 좌표를 클릭해서 게임 길찾기로 이동. 게임 창이 맨 앞일 때만 클릭한다(다른 창 오클릭 방지)."""

    def __init__(self, ue, pid):
        self.cam = Camera(ue).find()
        self.hwnd = game_hwnd(pid)
        self.rect, self.rect_at = None, 0.0
        self.last = 0.0

    def _safe(self, sx, sy):
        ox, oy, w, h = self.rect
        fx, fy = (sx - ox) / w, (sy - oy) / h
        if not (0.06 < fx < 0.94 and 0.10 < fy < 0.78):
            return False
        return not (fx > 0.78 and fy < 0.32)          # 오른쪽 위 미니맵·퀘스트 표시 피하기

    def click_world(self, pt, me, every=0.6):
        now = time.time()
        if now - self.last < every:
            return True
        if not self.hwnd or u32.GetForegroundWindow() != self.hwnd:
            return False
        if not self.rect or now - self.rect_at > 5:
            self.rect, self.rect_at = client_rect(self.hwnd), now
        c = self.cam.read()
        for t in (1.0, 0.8, 0.6, 0.45, 0.3):           # 화면 밖이면 내 쪽으로 당겨서 화면 안 점을 찍음
            p = tuple(me[i] + (pt[i] - me[i]) * t for i in range(3))
            sp = project(c, p, self.rect)
            if sp and self._safe(*sp):
                click(*sp)
                self.last = now
                return True
        return False

    def rclick_world(self, pt):
        """상호작용(우클릭)을 세계 점 위에. 게임 창이 앞일 때만."""
        if not self.hwnd or u32.GetForegroundWindow() != self.hwnd:
            return False
        if not self.rect:
            self.rect, self.rect_at = client_rect(self.hwnd), time.time()
        sp = project(self.cam.read(), pt, self.rect)
        if not sp or not self._safe(*sp):
            return False
        click(*sp, hold=0.08, right=True)
        return True
