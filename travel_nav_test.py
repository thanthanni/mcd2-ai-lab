"""빠른 이동 + 새 걷기 시험(10-22). 오프라인 영웅에서만(캐릭터가 움직임).

마을 역(Brave Haven)까지 nav.py로 걸어가서 → 빠른 이동으로 숲 전초기지(ForestA1-Outpost, 목록 3칸 아래)로 →
도착하면 그 역까지 걸어가서 → 빠른 이동으로 마을(목록 3칸 위)로 → … 를 시간 동안 반복.
빠른 이동 순서(10-22 travel_test로 확인): 역에 우클릭+A → 지도 열림 → X(광산 수레 정거장 목록, 초점은 지금 역) →
십자키 N번 → A → 확인 창 A → 로딩. 도착 확인은 '내 위치에서 가장 가까운 역 이름'.
결과 travel_nav_result.txt(시도마다 걷기 시간·이동 성공 여부), 실패하면 사진.
"""
from __future__ import annotations

import json
import math
import os
import struct
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, "travel_nav_result.txt")
TRACE = os.path.join(HERE, time.strftime("trace_%m%d_%H%M.jsonl"))
SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 1200.0
ROUTE = {"Brave Haven": ("ForestA1-Outpost", 3), "ForestA1-Outpost": ("Brave Haven", -3)}
lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


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
    import navmesh
    import nav as navmod
    from rule_bot import Bot, Pad
    gamewin.prepare()
    pad = Pad()
    ue = uemem.UE(winproc.Process(), rescan=True)
    bot = Bot(ue, pad)
    bot.clicker = screen.Clicker(ue, ue.p.pid)
    if not bot.r.player:
        log("내 캐릭터를 못 찾았어.")
        return
    gamewin.focus_game()
    time.sleep(2.5)
    for _ in range(2):
        pad.tap("B")
        time.sleep(0.4)
    bot.calibrate()

    def stations():
        out = {}
        for o in ue.find_instances("BP_MinecartStation_C"):
            try:
                props = ue.oprops(o)
                name = ue.fname(o + props["NameOnMap"].offset)
                rc = ue.q(o + props["RootComponent"].offset)
                out[name] = struct.unpack("<ddd", ue.read(rc + ue.field(rc, "RelativeLocation").offset, 24))
            except Exception:
                continue
        return out

    def mesh_fn():
        actor = next(o for o in ue.find_instances("LovikaRecastNavMesh") if not ue.objname(o).startswith("Default__"))
        return navmesh.NavMesh(navmesh.read_tiles(ue, actor))

    nav = navmod.Nav(bot.r, pad, bot.clicker, bot.to_stick, log, mesh_fn=mesh_fn)

    def shot(tag):
        try:
            import ctypes
            from PIL import ImageGrab
            if ctypes.windll.user32.GetForegroundWindow() != bot.clicker.hwnd:
                return
            x, y, w, h = screen.client_rect(bot.clicker.hwnd)
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            img.thumbnail((960, 540))
            img.save(os.path.join(HERE, time.strftime("tnav_%H%M%S_") + tag + ".jpg"), quality=60)
        except Exception:
            pass

    def walk(goal, limit):
        nav.goto(goal, tol=230)
        nav.path = []
        t0, st = time.time(), "moving"
        while time.time() - t0 < limit:
            tick = time.time()
            try:
                hp, _ = bot.r.hp(bot.r.player)
                if hp is not None and hp <= 0:
                    pad.reset()
                    return "died", time.time() - t0
                st = nav.step()
                if tick - getattr(walk, "tr", 0) > 0.5:
                    walk.tr = tick
                    me = bot.r.loc(bot.r.player)
                    with open(TRACE, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"t": round(tick, 1), "p": [round(v) for v in me], "mode": "tnav", "do": st}) + "\n")
                if st in ("arrived", "failed"):
                    break
            except Exception:
                log("오류:", traceback.format_exc(limit=2).strip().splitlines()[-1])
                time.sleep(0.3)
            time.sleep(max(0, 0.1 - (time.time() - tick)))
        pad.stick(0, 0)
        return (st if st != "moving" else "timeout"), time.time() - t0

    TABS = ["보관함", "수집품", "지도", "파티", "DLC", "시스템"]

    def active_tab():
        """메뉴 위쪽 탭 줄에서 주황 밑줄(y 6.8%) 가운데 x로 지금 탭 번호. 메뉴가 아니면 None.
        탭 가운데(화면 폭 비율): 보관함 .083 수집품 .161 지도 .240 파티 .317 DLC .396 시스템 .474"""
        try:
            from PIL import ImageGrab
            x, y, w, h = screen.client_rect(bot.clicker.hwnd)
            row = ImageGrab.grab(bbox=(x, y + int(h * 0.062), x + w // 2, y + int(h * 0.074)))
            px = row.load()
            xs = [i for i in range(row.width) for j in range(row.height)
                  if px[i, j][0] > 200 and 90 < px[i, j][1] < 190 and px[i, j][2] < 90]
            if len(xs) < 20:
                return None
            cx = (min(xs) + max(xs)) / 2 / w
            k = round((cx - 0.083) / 0.078)
            return k if 0 <= k < len(TABS) else None
        except Exception:
            return None

    def travel(st_pos, downs):
        pad.stick(0, 0)
        time.sleep(0.5)
        bot.clicker.rclick_world(st_pos)
        time.sleep(0.4)
        pad.tap("A")
        time.sleep(1.5)
        # 역 상호작용은 메뉴를 '마지막에 본 탭'으로 연다(19:5x 시험: 파티 탭으로 열려서 36번 다 실패) → 지도 탭으로 맞춤
        for _ in range(8):
            k = active_tab()
            log(f"  메뉴 탭 {TABS[k] if k is not None else '모름'}")
            if k is None:
                shot("tab_unknown")
                log("  탭 판별 실패: 확인 버튼을 누르지 않고 시험 중단")
                return False
            if k == 2:
                break
            pad.tap("RIGHT_SHOULDER" if k < 2 else "LEFT_SHOULDER")
            time.sleep(0.7)
        if active_tab() != 2:
            shot("tab_not_map")
            log("  지도 탭 전환 실패: 확인 버튼을 누르지 않고 시험 중단")
            return False
        shot("map")
        pad.tap("X")
        time.sleep(1.2)
        for _ in range(abs(downs)):
            pad.tap("DPAD_DOWN" if downs > 0 else "DPAD_UP")
            time.sleep(0.4)
        shot("pick")
        pad.tap("A")
        time.sleep(1.2)
        pad.tap("A")
        time.sleep(12)
        bot.r.scan()
        nav.mesh_t = 0                         # 새 곳 지도 바로 다시 읽기
        nav.prev = None
        return True

    t0, tries = time.time(), []
    log(f"빠른 이동 + 걷기 시험 {SECONDS:.0f}초")
    while time.time() - t0 < SECONDS - 60:
        S = stations()
        me = bot.r.loc(bot.r.player)
        here = min(S, key=lambda n: math.dist(S[n][:2], me[:2]))
        if here not in ROUTE:
            log(f"가까운 역이 {here}(시험 경로 밖) → 마을 역으로 걸어감")
            here = "Brave Haven"
        dest, downs = ROUTE[here]
        sp = S[here]
        d0 = math.dist(me[:2], sp[:2])
        res, sec = walk(sp, 60 + d0 / 250)
        rec = {"from": here, "walk": res, "walk_sec": round(sec), "walk_dist": round(d0)}
        if res != "arrived":
            shot("walkfail")
            log(f"[{len(tries) + 1}] {here} 역까지 걷기 {res} {sec:.0f}초")
            tries.append(rec)
            if res == "died":
                time.sleep(8)
                pad.tap("A")
                time.sleep(10)
            continue
        if not travel(sp, downs):
            rec["travel_error"] = "지도 탭 확인 실패"
            tries.append(rec)
            break
        me2 = bot.r.loc(bot.r.player)
        S2 = stations()
        got = min(S2, key=lambda n: math.dist(S2[n][:2], me2[:2]))
        rec.update({"travel_to": dest, "arrived_at": got, "ok": got == dest,
                    "dist_to_station": round(math.dist(S2[got][:2], me2[:2]))})
        if got != dest:
            shot("travelfail")
            for _ in range(3):                  # 열린 창 닫기
                pad.tap("B")
                time.sleep(0.4)
        tries.append(rec)
        log(f"[{len(tries)}] {here} 걷기 {sec:.0f}초({d0:.0f}) → 빠른 이동 {'성공' if got == dest else '실패'}: {got} "
            f"(역에서 {rec['dist_to_station']})")
    nav.save()
    pad.reset()
    bot.stop = True
    ok = sum(1 for t in tries if t.get("ok"))
    tr = sum(1 for t in tries if "ok" in t)
    wk = sum(1 for t in tries if t["walk"] == "arrived")
    log(f"\n[결과] 걷기 {wk}/{len(tries)}, 빠른 이동 {ok}/{tr}")
    for t in tries:
        log("  " + json.dumps(t, ensure_ascii=False))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    try:
        import glob
        import zipfile
        shots = glob.glob(os.path.join(HERE, "tnav_*.jpg"))
        if shots:
            with zipfile.ZipFile(os.path.join(HERE, time.strftime("snaps_tnav_%m%d_%H%M.zip")), "w") as z:
                for f in sorted(shots, key=os.path.getmtime)[-12:]:
                    z.write(f, os.path.basename(f))
            for f in shots:
                os.remove(f)
    except Exception as e:
        print("사진 묶기 실패", e)
    print("\n결과를 저장했어:", OUT)
