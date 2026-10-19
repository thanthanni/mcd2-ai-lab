"""길 안내선 2차 탐색(읽기만 함, 패드는 가상 패드로 왼쪽 스틱 누르기만 함).

봇처럼 진짜 패드를 빼고 실행한다. 가상 패드로 안내선을 켠 뒤 5초 동안 0.5초마다
안내선 관련 값(안내선 액터의 점 목록·스플라인, GCN_ShowGuidance 스플라인, NavigationPath들)을 적는다.
"""
from __future__ import annotations

import os
import struct
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "guide_probe2.txt")
sys.path.insert(0, HERE)
from state_probe import find_ohs_app  # noqa: E402

lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


def r3(v):
    return tuple(round(x) for x in v)


def spline_points(ue, comp):
    """SplineComponent.SplineCurves.Position.Points → [(InVal, (x,y,z))], 원소 크기를 InVal 0,1,2..로 확인."""
    off = ue.field(comp, "SplineCurves").offset
    data, num, mx = struct.unpack("<Qii", ue.read(comp + off, 16))
    if not data or num <= 0 or num > 5000:
        return [], 0
    for stride in (88, 96, 80, 104, 112):
        raw = ue.read(data, stride * min(num, 4))
        ins = [struct.unpack_from("<f", raw, i * stride)[0] for i in range(min(num, 4))]
        if all(abs(ins[i] - i) < 1e-3 for i in range(len(ins))):
            raw = ue.read(data, stride * num)
            return [(struct.unpack_from("<f", raw, i * stride)[0],
                     struct.unpack_from("<ddd", raw, i * stride + 8)) for i in range(num)], stride
    return [("?", ue.read(data, 48).hex())], -1


def comp_loc(ue, comp):
    try:
        return r3(struct.unpack("<ddd", ue.read(comp + ue.field(comp, "RelativeLocation").offset, 24)))
    except Exception:
        return None


def main():
    app = find_ohs_app()
    if not app:
        log("Offline Hero Sync 폴더를 못 찾았어.")
        return
    sys.path.insert(0, app)
    import winproc  # noqa
    import uemem    # noqa
    import vgamepad as vg
    ue = uemem.UE(winproc.Process(), rescan=True)
    pad = vg.VX360Gamepad()
    import gamewin
    gamewin.focus_game()
    time.sleep(0.5)

    def scan():
        me = trail = None
        gcns, navs = [], []
        for o in ue.iter_objects():
            try:
                n = ue.clsname(o)
                if ue.objname(o).startswith("Default__"):
                    continue
                if n == "BP_AlexCharacter_C" or (me is None and n.endswith("Character_C") and ue.is_a(o, "PlayerCharacter")):
                    me = o
                elif "GuidanceTrail" in n:
                    trail = o
                elif "ShowGuidance" in n:
                    gcns.append(o)
                elif n == "NavigationPath":
                    navs.append(o)
            except Exception:
                continue
        return me, trail, gcns, navs

    me, trail, gcns, navs = scan()
    log(f"처음: 안내선 액터 {'있음' if trail else '없음'}, ShowGuidance {len(gcns)}개, NavigationPath {len(navs)}개")
    pad.press_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB)
    pad.update()
    time.sleep(0.15)
    pad.release_button(vg.XUSB_BUTTON.XUSB_GAMEPAD_LEFT_THUMB)
    pad.update()
    log("왼쪽 스틱 누름")
    for k in range(10):
        time.sleep(0.5)
        if k in (0, 4):
            me, trail, gcns, navs = scan()
        log(f"\n--- {0.5 * (k + 1):.1f}초")
        try:
            r = ue.q(me + ue.field(me, "RootComponent").offset)
            log("내 위치", r3(struct.unpack("<ddd", ue.read(r + ue.field(r, "RelativeLocation").offset, 24))))
        except Exception:
            log("내 위치 읽기 실패")
        if trail:
            try:
                f = ue.field(trail, "GuidanceLinePositions").offset
                data, num, mx = struct.unpack("<Qii", ue.read(trail + f, 16))
                pts = [r3(struct.unpack("<ddd", ue.read(data + i * 24, 24))) for i in range(min(num, 12))] if data and 0 < num < 5000 else []
                st = ue.read(trail + ue.field(trail, "GuidanceLineStatus").offset, 2).hex()
                log(f"안내선 액터: 점 {num}개 상태 {st} 액터위치 {comp_loc(ue, ue.q(trail + ue.field(trail, 'RootComponent').offset))}", pts)
                sp = ue.q(trail + ue.field(trail, "Spline").offset)
                pp, stride = spline_points(ue, sp)
                log(f"  안내선 스플라인: 점 {len(pp)}개(원소 {stride}) 부품위치 {comp_loc(ue, sp)}", [(p[0], r3(p[1])) if p[0] != "?" else p for p in pp[:12]])
            except Exception as e:
                log("안내선 액터 읽기 실패", e)
        for g in gcns[:3]:
            try:
                log(f"ShowGuidance {ue.objname(g)} 위치 {comp_loc(ue, ue.q(g + ue.field(g, 'RootComponent').offset))}")
                for name, p in ue.oprops(g).items():
                    if p.kind == "ObjectProperty" and p.offset >= 0x2b0:
                        c = ue.q(g + p.offset)
                        if c and "Spline" in ue.clsname(c):
                            pp, stride = spline_points(ue, c)
                            log(f"  {name}({ue.clsname(c)}): 점 {len(pp)}개(원소 {stride}) 부품위치 {comp_loc(ue, c)}",
                                [(p2[0], r3(p2[1])) if p2[0] != "?" else p2 for p2 in pp[:12]])
            except Exception as e:
                log("ShowGuidance 읽기 실패", e)
        for o in navs:
            try:
                f = ue.field(o, "PathPoints").offset
                data, num, mx = struct.unpack("<Qii", ue.read(o + f, 16))
                if data and 0 < num < 5000:
                    a = r3(struct.unpack("<ddd", ue.read(data, 24)))
                    b = r3(struct.unpack("<ddd", ue.read(data + (num - 1) * 24, 24)))
                    log(f"NavPath {ue.objname(o)} 주인 {ue.objname(ue.outer(o))}: {num}점 {a} → {b}")
            except Exception:
                continue
    pad.reset()
    pad.update()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
    print("이 폴더에 생긴 guide_probe2.txt를 디스코드로 보내 줘.")
