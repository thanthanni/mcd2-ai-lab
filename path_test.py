"""갈 수 있는 곳 / 없는 곳 구별 시험(캐릭터가 조금 움직임 → 오프라인 프로필에서만 실행).

내 주변 16곳(8방향 × 900·1800)을 하나씩 클릭하고, 클릭할 때마다
- 0.6초 뒤 메모리의 NavigationPath 중 '내 발밑에서 시작하는 경로'의 점 수·끝점·끝점과 클릭 지점 거리
- 플레이어 컨트롤러에서 이름에 Path/Move/Dest/Goal/Cursor가 들어간 값
- 3초 뒤 실제로 클릭 지점에 얼마나 가까워졌는지
를 적는다. 게임이 '갈 수 있는 곳'에 경로를 만드는지, 못 가는 곳에선 경로가 짧게 끊기는지 확인하는 용도. 결과 path_test.txt.
"""
from __future__ import annotations

import math
import os
import struct
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "path_test.txt")
sys.path.insert(0, HERE)
from state_probe import find_ohs_app  # noqa: E402

KEYS = ("Path", "Move", "Dest", "Goal", "Cursor", "Click", "Target")
lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


def main():
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
    from guide_probe import value
    ue = uemem.UE(winproc.Process(), rescan=True)
    r = Reader(ue)
    r.scan()
    if not r.player:
        log("내 캐릭터를 못 찾았어.")
        return
    clicker = screen.Clicker(ue, ue.p.pid)
    gamewin.focus_game()
    time.sleep(0.8)

    pcs = [o for o in ue.find_instances("PlayerController")] or []
    try:
        pcs = [o for o in ue.iter_objects() if "PlayerController" in r._chain(ue.cls(o))[:4]
               and not ue.objname(o).startswith("Default__")]
    except Exception:
        pass
    pc = pcs[0] if pcs else None
    log("플레이어 컨트롤러:", ue.clsname(pc) if pc else "못 찾음")

    def pc_vals():
        out = {}
        if not pc:
            return out
        for name, pr in ue.oprops(pc).items():
            if any(k in name for k in KEYS) and "Delegate" not in pr.kind:
                try:
                    out[name] = value(ue, pc, pr)[:90]
                except Exception:
                    pass
        return out

    def navpaths(me):
        res = []
        for o in ue.iter_objects():
            try:
                if ue.clsname(o) != "NavigationPath" or ue.objname(o).startswith("Default__"):
                    continue
                f = ue.field(o, "PathPoints").offset
                data, num, mx = struct.unpack("<Qii", ue.read(o + f, 16))
                if not data or not 0 < num < 5000:
                    continue
                a = struct.unpack("<ddd", ue.read(data, 24))
                b = struct.unpack("<ddd", ue.read(data + (num - 1) * 24, 24))
                if math.hypot(a[0] - me[0], a[1] - me[1]) < 250:
                    res.append((o, num, a, b))
            except Exception:
                continue
        return res

    base = pc_vals()
    log("클릭 전 컨트롤러 값:", base)
    before = {o for o, *_ in navpaths(r.loc(r.player))}
    for dist in (900, 1800):
        for k in range(8):
            a = k * math.pi / 4
            me = r.loc(r.player)
            t = (me[0] + math.cos(a) * dist, me[1] + math.sin(a) * dist, me[2])
            ok = clicker.click_world(t, me, every=0)
            time.sleep(0.6)
            paths = navpaths(me)
            fresh = [p for p in paths if p[0] not in before]
            vals = pc_vals()
            changed = {kk: v for kk, v in vals.items() if base.get(kk) != v}
            time.sleep(2.4)
            now = r.loc(r.player)
            d0 = math.hypot(t[0] - me[0], t[1] - me[1])
            d1 = math.hypot(t[0] - now[0], t[1] - now[1])
            log(f"\n[{dist} {k * 45}도] 클릭 {'됨' if ok else '안 됨(화면 밖/창 뒤)'} 목표 {tuple(round(v) for v in t[:2])}"
                f"  3초 뒤 가까워진 거리 {d0 - d1:.0f} (남은 {d1:.0f}), 높이 변화 {now[2] - me[2]:.0f}")
            for o, num, pa, pb in (fresh or paths)[:3]:
                log(f"   경로{'(새것)' if o not in before else ''}: {num}점, 끝 {tuple(round(v) for v in pb)}, 끝↔목표 {math.hypot(pb[0] - t[0], pb[1] - t[1]):.0f}")
            if not paths:
                log("   내 발밑에서 시작하는 NavigationPath 없음")
            if changed:
                log("   바뀐 컨트롤러 값:", changed)
            before |= {o for o, *_ in paths}
            base = vals


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
