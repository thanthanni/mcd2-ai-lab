"""마우스 클릭 이동 시험: 카메라를 읽어 세계 좌표를 화면에 맞추고, 내 주변 4방향을 클릭해 실제로 그쪽으로 가는지 잰다.

넓은 곳에서 실행. 클릭할 때마다 1.5초 기다린 뒤 움직인 방향이 목표 방향과 얼마나 맞는지(코사인, 1이면 정확) 적는다.
결과는 click_probe.txt.
"""
from __future__ import annotations

import math
import os
import struct
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "click_probe.txt")
sys.path.insert(0, HERE)
from state_probe import find_ohs_app  # noqa: E402

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
    proc = winproc.Process()
    ue = uemem.UE(proc, rescan=True)
    r = Reader(ue)
    r.scan()
    cam = screen.Camera(ue).find()
    log("카메라 필드:", cam.f)
    hwnd = screen.game_hwnd(proc.pid)
    gamewin.focus_game(proc.pid)
    time.sleep(0.8)
    rect = screen.client_rect(hwnd)
    c = cam.read()
    log("게임 화면(왼쪽 위 x, y, 너비, 높이):", rect)
    log("카메라:", {k: (tuple(round(v) for v in c[k]) if k == "loc" else round(c[k], 2)) for k in c})
    me = r.loc(r.player)
    log("내 위치:", tuple(round(v) for v in me), "→ 화면", screen.project(c, me, rect))

    ok = 0
    for ang in (0, 90, 180, 270):
        me = r.loc(r.player)
        tgt = (me[0] + 600 * math.cos(math.radians(ang)), me[1] + 600 * math.sin(math.radians(ang)), me[2])
        c = cam.read()
        sp = screen.project(c, tgt, rect)
        if not sp:
            log(f"{ang}도: 화면 밖")
            continue
        screen.click(*sp)
        time.sleep(1.5)
        now = r.loc(r.player)
        mx, my = now[0] - me[0], now[1] - me[1]
        n = math.hypot(mx, my)
        cos = (mx * (tgt[0] - me[0]) + my * (tgt[1] - me[1])) / (n * 600) if n > 1 else 0
        log(f"{ang}도: 클릭 화면 {tuple(round(v) for v in sp)} 움직인 거리 {n:.0f} 방향 일치 {cos:.2f}")
        ok += cos > 0.8 and n > 200
    log(f"\n[결과] 4번 중 {ok}번 맞게 감" + (" → 클릭 이동 사용 가능" if ok >= 3 else " → 계산 확인 필요"))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
