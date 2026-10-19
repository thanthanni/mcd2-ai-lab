"""벽 너머(붉은 형체) 몹 구별 단서 찾기(읽기만 함).

언리얼은 화면에 실제로 그려진 시각(LastRenderTimeOnScreen 같은 값)을 부품마다 들고 있다.
벽에 가려진 몹은 이 값이 멈추고, 보이는 몹은 계속 오른다. 몹 몸통(Mesh) 부품의 앞쪽 메모리에서
1초에 약 1씩 오르는 숫자(float)를 찾아, 몹마다 그 숫자가 오르는지 멈췄는지 적는다.
몹 화면 위치도 같이 적으니까, 실행할 때 게임 화면을 캡처해서 어떤 몹이 붉은 형체였는지 맞춰 본다.
"""
from __future__ import annotations

import math
import os
import struct
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "occlusion_probe.txt")
sys.path.insert(0, HERE)
from state_probe import find_ohs_app  # noqa: E402

SPAN = 0x900
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
    import screen
    from state_reader import Reader
    proc = winproc.Process()
    ue = uemem.UE(proc, rescan=True)
    r = Reader(ue)
    r.scan()
    me = r.loc(r.player)
    cam = screen.Camera(ue).find()
    hwnd = screen.game_hwnd(proc.pid)
    rect = screen.client_rect(hwnd)
    c = cam.read()

    mobs = []
    for o, n in r.mobs.items():
        try:
            p = r.loc(o)
            d = math.hypot(p[0] - me[0], p[1] - me[1])
            if d > 2500:
                continue
            mesh = ue.q(o + ue.field(o, "Mesh").offset)
            sp = screen.project(c, p, rect)
            mobs.append({"o": o, "n": n, "d": d, "mesh": mesh, "sp": sp})
        except Exception:
            continue
    mobs.sort(key=lambda m: m["d"])
    mobs = mobs[:15]
    pl_mesh = ue.q(r.player + ue.field(r.player, "Mesh").offset)
    log(f"몹 {len(mobs)}마리(2500 안). 1초 간격으로 3번 읽어.")

    def snap():
        out = {}
        for m in mobs + [{"mesh": pl_mesh, "o": "me"}]:
            try:
                out[m["o"]] = ue.read(m["mesh"], SPAN)
            except Exception:
                pass
        return out

    s0 = snap()
    time.sleep(1.0)
    s1 = snap()
    time.sleep(1.0)
    s2 = snap()

    # 내 캐릭터(항상 보임) 몸통에서 1초에 0.8~1.2씩 두 번 연속 오른 float 위치 = 후보
    cands = []
    if "me" in s0 and "me" in s1 and "me" in s2:
        for off in range(0, SPAN - 4, 4):
            a, b, c2 = (struct.unpack_from("<f", s, off)[0] for s in (s0["me"], s1["me"], s2["me"]))
            if all(math.isfinite(v) for v in (a, b, c2)) and 10 < a < 1e7 and 0.8 < b - a < 1.2 and 0.8 < c2 - b < 1.2:
                cands.append(off)
    log("후보 위치(내 몸통에서 1초에 1씩 오르는 값):", [hex(x) for x in cands])

    log("\n[몹별] 이름 / 거리 / 화면 위치 / 후보마다 2초 동안 오른 양(2 근처=보임, 0=멈춤)")
    for m in mobs:
        o = m["o"]
        if o not in s0 or o not in s2:
            continue
        ups = []
        for off in cands:
            a = struct.unpack_from("<f", s0[o], off)[0]
            b = struct.unpack_from("<f", s2[o], off)[0]
            ups.append(f"{hex(off)}:{b - a:.1f}")
        sp = tuple(round(v) for v in m["sp"]) if m["sp"] else "화면 밖"
        log(f"  {m['n']} {m['d']:.0f} {sp} | " + " ".join(ups))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
