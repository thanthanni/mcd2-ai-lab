"""퀘스트 추적 시험(10-23): 키보드 J 짧게 = 퀘스트 일지, 일지에서 J 길게 = 추적, 휠 클릭 = 안내선(위키 조작표).
단계마다 사진 + QuestRunner.FocusedQuest/PlayerFocusedQuests + 안내선 점 수를 적는다. 패드는 안 만듦.
결과 quest_track_result.txt, 사진 snaps_quest_track.zip."""
from __future__ import annotations

import ctypes
import os
import struct
import sys
import time
import traceback
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, "quest_track_result.txt")
lines: list[str] = []
shots: list[str] = []
u32 = ctypes.windll.user32


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


def key(vk, hold=0.08):
    sc = u32.MapVirtualKeyW(vk, 0)
    u32.keybd_event(vk, sc, 0, 0)
    time.sleep(hold)
    u32.keybd_event(vk, sc, 2, 0)


def middle_click():
    u32.mouse_event(0x0020, 0, 0, 0, 0)
    time.sleep(0.08)
    u32.mouse_event(0x0040, 0, 0, 0, 0)


def main():
    from state_probe import find_ohs_app
    app = find_ohs_app()
    if not app:
        log("Offline Hero Sync 폴더를 못 찾았어.")
        return
    sys.path.insert(0, app)
    import winproc  # noqa
    import uemem    # noqa
    import gamewin
    import screen
    from state_reader import Reader
    ue = uemem.UE(winproc.Process(), rescan=True)
    r = Reader(ue)
    r.scan()
    hwnd = screen.game_hwnd(ue.p.pid)
    gamewin.focus_game()
    time.sleep(1.5)

    def shot(tag):
        try:
            from PIL import ImageGrab
            if u32.GetForegroundWindow() != hwnd:
                log("  (사진 생략: 게임 창이 앞이 아님)")
                return
            x, y, w, h = screen.client_rect(hwnd)
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            img.thumbnail((1280, 720))
            p = os.path.join(HERE, f"qt_{len(shots):02d}_{tag}.jpg")
            img.save(p, quality=70)
            shots.append(p)
        except Exception as e:
            log("  사진 실패", e)

    def val(a, p):
        k = p.kind
        if k == "ObjectProperty":
            x = ue.q(a)
            if not x:
                return "없음"
            s = f"{ue.clsname(x)}:{ue.objname(x)[:40]}"
            pr = ue.oprops(x)
            if "ID" in pr:
                s += " ID=" + (ue.fname(x + pr["ID"].offset) if pr["ID"].kind == "NameProperty" else repr(ue.fstring(x + pr["ID"].offset)))
            return s
        if k == "ArrayProperty":
            data, num, mx = struct.unpack("<Qii", ue.read(a, 16))
            if not data or not 0 <= num < 100:
                return "[]"
            inner = p.inner
            out = []
            for i in range(min(num, 6)):
                ea = data + i * inner.size
                if inner.kind == "StructProperty":
                    parts = []
                    for n, q in sorted(ue.props(inner.struct).items(), key=lambda kv: kv[1].offset):
                        if q.kind == "NameProperty":
                            parts.append(f"{n}={ue.fname(ea + q.offset)}")
                        elif q.kind == "StrProperty":
                            parts.append(f"{n}={ue.fstring(ea + q.offset)!r}")
                        elif q.kind == "ObjectProperty":
                            parts.append(f"{n}={ue.objname(ue.q(ea + q.offset))[:30] if ue.q(ea + q.offset) else '없음'}")
                    out.append("{" + ", ".join(parts) + "}")
                else:
                    out.append(inner.kind)
            return f"[{num}개 " + " ".join(out) + "]"
        if k == "NameProperty":
            return ue.fname(a)
        if k == "StrProperty":
            return repr(ue.fstring(a))
        return k

    def state(tag):
        try:
            runner = next(o for o in ue.find_instances("BP_QuestRunner_C") if not ue.objname(o).startswith("Default__"))
            pr = ue.oprops(runner)
            got = {n: val(runner + pr[n].offset, pr[n]) for n in ("FocusedQuest", "PlayerFocusedQuests") if n in pr}
        except Exception as e:
            got = {"오류": str(e)[:80]}
        try:
            r.scan()
            me = r.loc(r.player)
            pts, kind = r.guide_path(me[:2])
            g = f"안내선 {kind} {len(pts)}점 끝 {tuple(round(v) for v in pts[-1])}" if pts else "안내선 없음"
        except Exception as e:
            g = f"안내선 읽기 실패 {str(e)[:60]}"
        log(f"[{tag}] {got} | {g}")

    VK_J = 0x4A
    state("처음")
    shot("start")
    key(VK_J)                       # 일지 열기
    time.sleep(1.8)
    shot("log_open")
    state("일지 연 뒤")
    key(VK_J, hold=1.5)             # 길게 = 추적
    time.sleep(1.2)
    shot("after_hold")
    state("J 길게 뒤")
    if u32.GetForegroundWindow() == hwnd:
        key(0x1B)                   # Esc로 일지 닫기
    time.sleep(1.2)
    shot("closed")
    state("닫은 뒤")
    if u32.GetForegroundWindow() == hwnd:
        middle_click()              # 안내선
    time.sleep(2.0)
    shot("guide")
    state("휠 클릭 뒤")
    time.sleep(2.0)
    state("2초 더")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    open(OUT, "w", encoding="utf-8").write("\n".join(lines))
    if shots:
        with zipfile.ZipFile(os.path.join(HERE, "snaps_quest_track.zip"), "w") as z:
            for p in shots:
                z.write(p, os.path.basename(p))
        for p in shots:
            os.remove(p)
