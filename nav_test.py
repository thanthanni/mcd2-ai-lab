"""걷기 시험(10-22): 새 걷기 담당(nav.py)만 따로 돌려서 도착률을 잰다. 오프라인 영웅에서만(캐릭터가 움직임).

정해 둔 길을 시간 동안 계속 오간다: 마을 수레역(Brave Haven) → 북쪽 필드(봇이 자주 싸우던 곳) → 마을 수레역 → …
구간마다 도착/실패·걸린 시간·막힘 횟수를 nav_result.txt에, 0.5초마다 위치를 trace_*.jsonl에(다음 지도 만들 때 씀) 남긴다.
싸움은 안 하고, 맞으면서 몹이 바로 붙어 있을 때만 잠깐 때린다. 체력 40% 아래면 물약, 죽으면 기다렸다가 A.
판단 기준: 도착 90% 이상.
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
OUT = os.path.join(HERE, "nav_result.txt")
TRACE = os.path.join(HERE, time.strftime("trace_%m%d_%H%M.jsonl"))
SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 600.0
FIELD = (19518, 12759, 4512)          # 10-22 기록: 마을 북쪽 필드, 봇이 자주 싸우던 자리
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
    from rule_bot import Bot, Pad, PASSIVE
    import nav as navmod
    gamewin.prepare()
    pad = Pad()
    ue = uemem.UE(winproc.Process(), rescan=True)
    bot = Bot(ue, pad)                     # 상태 훑기(3초마다)·스틱 방향만 씀, 판단은 안 씀
    bot.clicker = screen.Clicker(ue, ue.p.pid)
    if not bot.r.player:
        log("내 캐릭터를 못 찾았어.")
        return
    gamewin.focus_game()
    time.sleep(2.5)                        # 새 가상 패드를 게임이 알아차릴 시간
    for _ in range(2):
        pad.tap("B")
        time.sleep(0.4)
    bot.calibrate()

    station = None
    for o in ue.find_instances("BP_MinecartStation_C"):
        try:
            props = ue.oprops(o)
            if ue.fname(o + props["NameOnMap"].offset) != "Brave Haven":
                continue
            rc = ue.q(o + props["RootComponent"].offset)
            station = struct.unpack("<ddd", ue.read(rc + ue.field(rc, "RelativeLocation").offset, 24))
        except Exception:
            continue
    station = station or (14819.0, -5500.0, 4663.0)
    legs = [("역", station), ("필드", FIELD)]
    mesh_fn = None
    try:
        import navmesh
        actor = next(o for o in ue.find_instances("LovikaRecastNavMesh") if not ue.objname(o).startswith("Default__"))
        m0 = navmesh.read_navmesh(ue, actor)
        log(f"게임 길찾기 지도 읽음: 다각형 {len(m0)}개")
        mesh_fn = lambda: navmesh.read_navmesh(ue, actor)   # noqa: E731
    except Exception as e:
        log("게임 길찾기 지도 못 읽음(걸어 본 길 지도만 씀):", e)
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
            img.save(os.path.join(HERE, time.strftime("nav_%H%M%S_") + tag + ".jpg"), quality=60)
        except Exception:
            pass

    me = bot.r.loc(bot.r.player)
    k = 0 if math.dist(me[:2], station[:2]) > 1500 else 1     # 역 근처에서 시작하면 필드부터
    results, t0, last_tr = [], time.time(), 0.0
    log(f"걷기 시험 {SECONDS:.0f}초, 시작 {tuple(round(v) for v in me)}")
    while time.time() - t0 < SECONDS:
        name, goal = legs[k % 2]
        me = bot.r.loc(bot.r.player)
        dist0 = math.dist(me[:2], goal[:2])
        limit = 60 + dist0 / 250
        nav.goto(goal, tol=300)
        ls, st, died, fights = time.time(), "moving", 0, 0
        stats0 = dict(nav.stats)
        log(f"[구간 {len(results) + 1}] {name}까지 {dist0:.0f} (제한 {limit:.0f}초)")
        hp_prev, fight_until = None, 0.0
        while time.time() - t0 < SECONDS and time.time() - ls < limit:
            tick = time.time()
            try:
                with bot.lock:
                    mobs = dict(bot.r.mobs)
                me = bot.r.loc(bot.r.player)
                hp, hpm = bot.r.hp(bot.r.player)
                if hp is not None and hp <= 0:            # 죽음: 기다렸다가 A, 되살아나면 그 자리부터 다시
                    died += 1
                    pad.reset()
                    shot("dead")
                    td = time.time()
                    while time.time() - td < 40:
                        time.sleep(1)
                        h2, _ = bot.r.hp(bot.r.player) if bot.r.player else (None, None)
                        if h2 and h2 > 0:
                            break
                        if time.time() - td > 6:
                            pad.tap("A")
                    time.sleep(3)
                    nav.goto(goal, tol=300)
                    nav.path = []
                    continue
                if hp is not None and hpm and hp / hpm < 0.4 and (bot.r.attr(bot.r.player, "ATR_Health", "HealthPotionCharges") or 0) >= 1 \
                        and tick - getattr(bot, "last_potion", 0) > 3:
                    pad.trigger(left=True)
                    bot.last_potion = tick
                hurt = hp_prev is not None and hp is not None and hp < hp_prev - 0.5
                hp_prev = hp
                close = None
                for o, n in mobs.items():
                    if any(p in n for p in PASSIVE):
                        continue
                    try:
                        mp = bot.r.loc(o)
                        mh, _ = bot.r.hp(o)
                    except Exception:
                        continue
                    if mh and mh > 0 and math.dist(mp[:2], me[:2]) < 280 and abs(mp[2] - me[2]) < 250:
                        close = mp
                        break
                if close and (hurt or tick < fight_until):    # 붙어서 때리는 몹만 잠깐 상대(걷기 시험이라 싸움은 최소)
                    if hurt:
                        fight_until = tick + 3
                        fights += 1
                    pad.stick(*bot.to_stick(close[0] - me[0], close[1] - me[1], 0.25))
                    pad.tap("X")
                    nav.best_t = tick                            # 싸우는 동안은 막힘으로 안 셈
                else:
                    st = nav.step()
                if tick - last_tr > 0.5:
                    last_tr = tick
                    with open(TRACE, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"t": round(tick, 1), "p": [round(v) for v in me], "hp": hp, "mode": "nav",
                                            "do": st, "lv": nav.level}) + "\n")
                if nav.stats["wedge"] > stats0.get("wedge", 0) and not getattr(nav, "_shot_w", False):
                    shot("wedge")
                    nav._shot_w = True
                if st in ("arrived", "failed"):
                    break
            except Exception:
                log("오류:", traceback.format_exc(limit=2).strip().splitlines()[-1])
                time.sleep(0.3)
            time.sleep(max(0, 0.1 - (time.time() - tick)))
        nav._shot_w = False
        pad.stick(0, 0)
        me = bot.r.loc(bot.r.player)
        took = time.time() - ls
        if st != "arrived":
            shot("fail")
            st = "failed" if st == "failed" else ("timeout" if time.time() - t0 < SECONDS else "cut")
        d = {k2: nav.stats[k2] - stats0.get(k2, 0) for k2 in nav.stats}
        rec = {"leg": name, "result": st, "sec": round(took), "start_dist": round(dist0),
               "left": round(math.dist(me[:2], goal[:2])), "died": died, "fights": fights, **d}
        results.append(rec)
        log(f"  → {st} {took:.0f}초, 남은 거리 {rec['left']}, 막힘 점프 {d['jumps']} 돌기 {d['detours']} "
            f"끼임 {d['wedge']} 다시찾기 {d['replans']} 사망 {died} 싸움 {fights} 경로(게임지도/걸어본길) {d['mesh_paths']}/{d['wm_paths']}")
        k += 1
    nav.save()
    pad.reset()
    bot.stop = True
    done = [r for r in results if r["result"] != "cut"]
    ok = sum(r["result"] == "arrived" for r in done)
    log(f"\n[결과] 구간 {len(done)}개 중 도착 {ok}개 ({100 * ok / max(1, len(done)):.0f}%), 배운 칸 {nav.stats['learned_cells']}")
    for r in results:
        log("  " + json.dumps(r, ensure_ascii=False))


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
        shots = glob.glob(os.path.join(HERE, "nav_*.jpg"))
        if shots:
            with zipfile.ZipFile(os.path.join(HERE, time.strftime("snaps_nav_%m%d_%H%M.zip")), "w") as z:
                for f in sorted(shots)[-12:]:
                    z.write(f, os.path.basename(f))
            for f in shots:
                os.remove(f)
    except Exception as e:
        print("사진 묶기 실패", e)
    print("\n결과를 저장했어:", OUT)
