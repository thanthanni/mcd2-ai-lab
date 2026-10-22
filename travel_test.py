"""빠른 이동 시험(캐릭터가 움직임 → 오프라인 프로필에서만). 결과 travel_test.txt + travel_*.jpg.

1) 마을 수레역(Brave Haven)까지 클릭 이동  2) 역에 상호작용(우클릭 + A) → '광산 수레 정거장' 창
3) 십자키 아래를 N번(인자, 기본 3) 눌러 목록에서 고르고 A  4) 10초 뒤 내 위치에서 가장 가까운 역 이름 = 실제 도착한 곳
화면 목록 순서(10-22 장훈 캡처): 안식처 정거장 / 벌집 농장, 허니브룩 다리 / 리틀 하울 촌락, 깊은 어둠 입구, 벌목꾼 전초기지 / 비의 평원 …
목록 순서와 메모리 역 이름(ForestA1-DangerZone 등)의 짝을 확인하는 용도.
"""
from __future__ import annotations

import math
import os
import struct
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "travel_test.txt")
sys.path.insert(0, HERE)
from state_probe import find_ohs_app  # noqa: E402

lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


def main():
    downs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
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
    from rule_bot import Pad
    ue = uemem.UE(winproc.Process(), rescan=True)
    r = Reader(ue)
    r.scan()
    pad = Pad()
    clicker = screen.Clicker(ue, ue.p.pid)
    gamewin.focus_game()
    time.sleep(0.8)
    for _ in range(3):                                   # 지난번에 열린 채 남은 창(빠른 이동 확인 등) 닫기
        pad.tap("B")
        time.sleep(0.4)

    def shot(tag):
        try:
            from PIL import ImageGrab
            x, y, w, h = screen.client_rect(clicker.hwnd)
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            img.thumbnail((960, 540))
            img.save(os.path.join(HERE, f"travel_{tag}.jpg"), quality=70)
        except Exception as e:
            log("사진 실패", e)

    stations = []
    for o in ue.find_instances("BP_MinecartStation_C"):
        try:
            props = ue.oprops(o)
            name = ue.fname(o + props["NameOnMap"].offset)
            rc = ue.q(o + props["RootComponent"].offset)
            p = struct.unpack("<ddd", ue.read(rc + ue.field(rc, "RelativeLocation").offset, 24))
            stations.append((name, p, o))
        except Exception:
            continue
    log(f"수레역 {len(stations)}개")

    def nearest(p):
        return min(stations, key=lambda s: math.hypot(s[1][0] - p[0], s[1][1] - p[1]))

    me = r.loc(r.player)
    home = [s for s in stations if s[0] == "Brave Haven"]
    if not home:
        log("마을 역을 못 찾았어")
        return
    hp = home[0][1]
    log("시작 위치", tuple(round(v) for v in me), "마을 역까지", round(math.hypot(hp[0] - me[0], hp[1] - me[1])))
    t0 = time.time()
    while time.time() - t0 < 60:                         # 1) 역까지 걸어가기
        me = r.loc(r.player)
        d = math.hypot(hp[0] - me[0], hp[1] - me[1])
        if d < 250:
            break
        clicker.click_world(hp, me, every=0.6)
        time.sleep(0.3)
    me = r.loc(r.player)
    log("역 앞 도착", round(math.hypot(hp[0] - me[0], hp[1] - me[1])), f"{time.time() - t0:.0f}초")
    pad.stick(0, 0)
    time.sleep(0.5)
    clicker.rclick_world(hp)                             # 2) 상호작용
    time.sleep(0.4)
    pad.tap("A")
    time.sleep(1.5)
    shot("map")                                          # 패드 모드: 역에 상호작용하면 지도가 열림(아래쪽 'X 광산 수레 정거장')
    pad.tap("X")                                         # 3) 정거장 목록 열기 → 십자키 아래 N번 → A(선택) → 확인 창에서 A(빠른 이동)
    time.sleep(1.2)
    shot("list")
    for _ in range(downs):
        pad.tap("DPAD_DOWN", hold=0.08)
        time.sleep(0.4)
    shot("pick")
    pad.tap("A")
    time.sleep(1.2)
    shot("confirm")
    pad.tap("A")
    log(f"X → 십자키 아래 {downs}번 → A → 확인 A")
    time.sleep(12)                                       # 4) 이동·로딩 기다리기
    shot("after")
    r.scan()
    me = r.loc(r.player)
    n = nearest(me)
    log("도착 위치", tuple(round(v) for v in me), "가장 가까운 역", n[0], round(math.hypot(n[1][0] - me[0], n[1][1] - me[1])))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    try:                                                 # 사진은 snaps_*.zip 이름으로 묶어야 자동 실행기가 보냄
        import glob
        import zipfile
        shots = glob.glob(os.path.join(HERE, "travel_*.jpg"))
        if shots:
            with zipfile.ZipFile(os.path.join(HERE, time.strftime("snaps_travel_%m%d_%H%M.zip")), "w") as z:
                for f in shots:
                    z.write(f, os.path.basename(f))
            for f in shots:
                os.remove(f)
    except Exception as e:
        print("사진 묶기 실패", e)
    print("\n결과를 저장했어:", OUT)
