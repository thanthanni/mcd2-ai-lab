"""조사(10-24, 장훈 '진행시켜'): 캐릭터 주변을 읽기만 해서 한 번에 뽑는다. 조작 없음.
1) 주변 R 안 액터를 클래스별로 세고, 물·죽는 구역·사다리·다리·문·상호작용 같은 이름은 위치·크기까지
2) 게임 길찾기 지도(내비 메시) 다각형의 땅 종류 번호(area)별 개수와 내 근처 예시
3) 사진 1장. 결과 area_probe.txt(+ area_probe.jsonl 전체 목록), snaps_area_probe.zip"""
from __future__ import annotations

import collections
import json
import math
import os
import struct
import sys
import time
import traceback
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, "area_probe.txt")
JL = os.path.join(HERE, "area_probe.jsonl")
R = float(sys.argv[1]) if len(sys.argv) > 1 else 8000.0
KEYS = ("water", "kill", "death", "pain", "volume", "ladder", "climb", "vine", "rope", "bridge", "swim", "lift",
        "elevator", "door", "gate", "lever", "interact", "jump", "teleport", "portal", "boat", "mine", "rail",
        "cart", "barrier", "block", "wall", "trigger", "quest", "destination", "explore", "puzzle", "golem", "tuner")
lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    from state_probe import find_ohs_app
    app = find_ohs_app()
    sys.path.insert(0, app)
    import winproc  # noqa
    import uemem    # noqa
    import screen
    import gamewin
    import navmesh
    from state_reader import Reader
    ue = uemem.UE(winproc.Process(), rescan=True)
    r = Reader(ue)
    r.scan()
    me = r.loc(r.player)
    log(f"내 위치 {tuple(round(v) for v in me)}, 반경 {R:.0f}")

    counts = collections.Counter()
    found, nav_actor = [], None
    t0 = time.time()
    seen = 0
    for o in ue.iter_objects():
        if time.time() - t0 > 90:
            log(f"(훑기 90초 넘어 {seen}개에서 멈춤)")
            break
        seen += 1
        try:
            name = ue.objname(o)
            if name.startswith("Default__"):
                continue
            ch = r._chain(ue.cls(o))
            if not ch or "Actor" not in ch:
                continue
            if ch[0] == "LovikaRecastNavMesh":
                nav_actor = o
            try:
                p = r.loc(o)
            except Exception:
                continue
            d = math.dist(p[:2], me[:2])
            if d > R:
                continue
            counts[ch[0]] += 1
            low = (ch[0] + " " + name).lower()
            if any(k in low for k in KEYS):
                rec = {"d": round(d), "cls": ch[0], "name": name[:90], "p": [round(v) for v in p],
                       "chain": ch[1:5]}
                try:
                    rc = ue.q(o + r._off(o, "RootComponent"))
                    rec["scale"] = [round(v, 2) for v in struct.unpack("<ddd", ue.read(rc + r._off(rc, "RelativeScale3D"), 24))]
                except Exception:
                    pass
                found.append(rec)
        except Exception:
            continue
    log(f"훑은 객체 {seen}개, {time.time() - t0:.0f}초, 반경 안 액터 {sum(counts.values())}개")
    log("\n[반경 안 액터 클래스 상위 60]")
    for c, n in counts.most_common(60):
        log(f"  {n:4d} {c}")
    found.sort(key=lambda x: x["d"])
    log(f"\n[관심 이름(물·죽는 구역·사다리·다리·문·상호작용 등) {len(found)}개, 가까운 80개]")
    for x in found[:80]:
        log(f"  {x['d']:6d} {x['cls']} {x['name'][:60]} {tuple(x['p'])} 크기{tuple(x.get('scale', []))} 위:{'/'.join(x['chain'][:3])}")
    with open(JL, "w", encoding="utf-8") as f:
        for x in found:
            f.write(json.dumps(x, ensure_ascii=False) + "\n")

    if nav_actor:
        try:
            m = navmesh.read_navmesh(ue, nav_actor)
            hist = collections.Counter(m.area)
            log(f"\n[길찾기 지도 다각형 {len(m)}개 땅 종류(area)별]")
            for a, n in sorted(hist.items()):
                near = sorted((math.dist(m.center[i][:2], me[:2]), i) for i in range(len(m)) if m.area[i] == a)[:3]
                ex = ", ".join(f"{tuple(round(v) for v in m.center[i])}({dd:.0f})" for dd, i in near)
                log(f"  area {a:2d}: {n:5d}개  가까운 예: {ex}")
            log(f"  단차 연결 {len(m.jump_edges)}개")
        except Exception as e:
            log("길찾기 지도 못 읽음:", e)
    else:
        log("길찾기 지도 액터 못 찾음")

    try:
        from PIL import ImageGrab
        hwnd = screen.game_hwnd(ue.p.pid)
        gamewin.focus_game()
        time.sleep(1.0)
        x, y, w, h = screen.client_rect(hwnd)
        img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
        img.thumbnail((1600, 900))
        sp = os.path.join(HERE, "area_probe.jpg")
        img.save(sp, quality=75)
        with zipfile.ZipFile(os.path.join(HERE, "snaps_area_probe.zip"), "w") as z:
            z.write(sp, "area_probe.jpg")
        os.remove(sp)
    except Exception as e:
        log("사진 실패", e)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
