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
PROBE = "probe" in sys.argv[2:]
LIST = "list" in sys.argv[2:]
QUEST = "quest" in sys.argv[2:]
FOLLOW = "follow" in sys.argv[2:]
# 역 목록 순서(10-24 확인: 53 사진 + 좌표 대조). 목록은 지금 역에 커서가 있고 아래로 갈수록 번호가 큼.
STATIONS = {"Brave Haven": (0, (14819, -5500, 4500)), "PlainsA1-Barn": (1, (29000, 36881, 4300)),
            "PlainsA1-Border": (2, (17100, 39081, 2500)), "ForestA1-Outpost": (3, (13519, 61401, 2000)),
            "ForestA1-SpiderCaveExit": (4, (27018, 54700, 1400)), "ForestA1-DangerZone": (5, (14518, 83301, 1400)),
            "PlainsA2-VillagerOasis": (6, (-11181, 70100, 600))}
GOTO = next((a.split(":", 1)[1] for a in sys.argv[2:] if a.startswith("goto:")), None)   # 예) goto:ForestA1-DangerZone   # 추적 중인 퀘스트 안내선(휠 클릭)을 따라 걷기(10-23 스프린트3)   # 웅덩이 연못(목록 6칸 아래)으로 빠른 이동 → 메인 퀘스트 주민 찾아 말 걸기(10-23 스프린트2)
OASIS = (-11181, 70100, 600)       # PlainsA2-VillagerOasis(웅덩이 연못으로 추정) 역 위치
     # 역에 도착하면 역 목록만 사진으로 훑고 끝(빠른 이동 안 함)   # 역에 도착하면 빠른 이동 대신 상호작용 입력 시험만
ROUTE = {"Brave Haven": ("ForestA1-Outpost", 3), "ForestA1-Outpost": ("Brave Haven", -3)}
if QUEST:   # 목록 순서(10-23 53_station_list): 0 안식처 1 벌집 농장 2 허니브룩 다리 3 리틀 하울(=ForestA1-Outpost) 4 깊은 어둠 5 벌목꾼 6 웅덩이 연못
    ROUTE = {"Brave Haven": ("PlainsA2-VillagerOasis", 6), "ForestA1-Outpost": ("PlainsA2-VillagerOasis", 3)}
lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)
    try:   # 중간에 멈춰 강제 종료돼도 여기까지는 남게(10-23 follow 판이 56초 뒤 멈춰 결과 0줄)
        with open(OUT, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except OSError:
        pass


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
    from rule_bot import Bot, Pad, PASSIVE
    gamewin.prepare()
    # 지난 판 가상 패드가 빠지며 남긴 연결 해제 창은 새 패드가 생기기 전에 키보드로 닫아야 닫힘
    # (10-24: 새 패드 연결 뒤엔 A·클릭·스페이스 모두 무시, 10-23 01:40엔 패드 없이 스페이스로 닫힘)
    gamewin.focus_game()
    try:
        gamewin.dismiss_controller_prompt(None)
    except Exception as e:
        log("연결 해제 창(패드 만들기 전) 닫기 실패:", e)
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

    modal_t = {"t": 0.0}

    def modal_guard(every=5.0):
        """연결 해제 창(0014)이 늦게 떠서 시작할 때 3초 검사로는 놓침(10-24: 떠 있는 채로 L3·휠 클릭 다 무시)
        → every초마다 화면 한 장으로 확인하고, 떠 있으면 닫기 처리."""
        now = time.time()
        if now - modal_t["t"] < every:
            return
        modal_t["t"] = now
        try:
            from pathlib import Path
            from PIL import Image, ImageGrab
            hwnd = bot.clicker.hwnd
            if screen.u32.GetForegroundWindow() != hwnd:
                return
            x, y, w, h = screen.client_rect(hwnd)
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            with Image.open(Path(gamewin.__file__).with_name("controller_disconnected.png")) as tpl:
                if gamewin.controller_prompt_matches(img, tpl):
                    log("  [창] 컨트롤러 연결 해제 창 발견 → 닫기")
                    gamewin.dismiss_controller_prompt(pad)
        except Exception as e:
            log("  [창] 확인 실패:", e)

    inst_cache: dict[str, list] = {}

    def instances(name, budget=8.0):
        """클래스 이름이 name인 객체 목록. uemem.find_instances가 걷는 중(새 구역 불러오는 중) 안 끝나는 일이 있어서
        (10-24 tnav_hang: find_instances에서 40분) 직접 훑되 budget초 넘으면 거기까지만. 찾은 목록은 기억해 두고 다시 씀."""
        if inst_cache.get(name):
            return inst_cache[name]
        out, t0 = [], time.time()
        for o in ue.iter_objects():
            if time.time() - t0 > budget:
                log(f"  ({name} 찾기 {budget:.0f}초 넘어 {len(out)}개에서 멈춤)")
                break
            try:
                if ue.clsname(o) == name and not ue.objname(o).startswith("Default__"):
                    out.append(o)
            except Exception:
                continue
        if out:
            inst_cache[name] = out
        return out

    def stations():
        out = {}
        for o in instances("BP_MinecartStation_C"):
            try:
                props = ue.oprops(o)
                name = ue.fname(o + props["NameOnMap"].offset)
                rc = ue.q(o + props["RootComponent"].offset)
                out[name] = struct.unpack("<ddd", ue.read(rc + ue.field(rc, "RelativeLocation").offset, 24))
            except Exception:
                continue
        return out

    mesh_actor = {"o": None}

    def mesh_fn():
        # 20초마다 객체 13만 개를 다시 뒤지던 찾기가 10-23/24 따라가기 판에서 40분 넘게 안 끝남(tnav_hang: find_instances)
        # → 한 번 찾은 지도 액터를 계속 쓰고, 다시 찾을 땐 8초 넘으면 이번 갱신은 포기
        a = mesh_actor["o"]
        if a:
            try:
                return navmesh.read_navmesh(ue, a)
            except Exception:
                mesh_actor["o"] = None
        t0 = time.time()
        for o in ue.iter_objects():
            if time.time() - t0 > 8:
                raise TimeoutError("게임 지도 액터 찾기 8초 넘음")
            try:
                if ue.clsname(o) == "LovikaRecastNavMesh" and not ue.objname(o).startswith("Default__"):
                    mesh_actor["o"] = o
                    break
            except Exception:
                continue
        else:
            raise LookupError("게임 지도 액터 없음")
        log(f"[걷기] 게임 지도 액터 찾음 {time.time() - t0:.1f}초")
        return navmesh.read_navmesh(ue, mesh_actor["o"])

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
        budget_set = False
        hp_prev, fight_until, last_wedge = None, 0.0, nav.stats["wedge"]
        while time.time() - t0 < limit and time.time() < run_deadline:
            modal_guard()
            survive()
            tick = time.time()
            try:
                hp, hpm = bot.r.hp(bot.r.player)
                if hp is not None and hp <= 0:
                    pad.reset()
                    return "died", time.time() - t0
                # nav_test에서 확인했던 최소 생존 대응: 물약 + 붙어서 피해를 주는 적만 반격.
                # 체력이 그대로인데 3초마다 물약을 누르던 문제(10-24: 111.9/최대값 37%로 106번) → 최근 맞았을 때만, 물약 쿨 30초
                hurt = hp_prev is not None and hp is not None and hp < hp_prev - 1
                if hurt:
                    bot.last_hurt = tick
                if hp is not None and hpm and hp / hpm < 0.4 and tick - getattr(bot, "last_hurt", 0) < 5 \
                        and (bot.r.attr(bot.r.player, "ATR_Health", "HealthPotionCharges") or 0) >= 1 and tick - bot.last_potion > 30:
                    pad.trigger(left=True)
                    bot.last_potion = tick
                    log("[이동] 물약 사용")
                hurt = hp_prev is not None and hp is not None and hp < hp_prev - 0.5
                hp_prev = hp
                close = None
                me = bot.r.loc(bot.r.player)
                with bot.lock:
                    mobs = dict(bot.r.mobs)
                for o, name in mobs.items():
                    if any(n in name for n in PASSIVE):
                        continue
                    try:
                        mp = bot.r.loc(o)
                        mh, _ = bot.r.hp(o)
                        if mh and mh > 0 and math.dist(mp[:2], me[:2]) < 280 and abs(mp[2]-me[2]) < 250:
                            close = mp
                            break
                    except Exception:
                        continue
                if close and (hurt or tick < fight_until):
                    if hurt:
                        fight_until = tick + 3
                    pad.stick(*bot.to_stick(close[0]-me[0], close[1]-me[1], 0.25))
                    pad.tap("X")
                    nav.best_t = tick
                else:
                    st = nav.step()
                if nav.stats["wedge"] > last_wedge:
                    shot("wedge")
                    last_wedge = nav.stats["wedge"]
                if not budget_set and nav.path:
                    limit = max(limit, 60 + nav.remaining(bot.r.loc(bot.r.player)) / 250)
                    budget_set = True
                if tick - getattr(walk, "tr", 0) > 0.5:
                    walk.tr = tick
                    me = bot.r.loc(bot.r.player)
                    with open(TRACE, "a", encoding="utf-8") as f:
                        f.write(json.dumps({"t": round(tick, 1), "p": [round(v) for v in me], "mode": "tnav", "do": st, "hp":hp, "waypoint":nav.i, "path_points":len(nav.path)}) + "\n")
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
        # 역 메뉴는 역을 좌클릭해야 열림(10-23 51_station_check: A 짧게·길게, 우클릭, 우클릭+A 모두 안 열림)
        # → 메뉴가 안 열렸을 때만 다시 클릭(열린 메뉴 위 클릭은 항목 선택이 될 수 있음)
        c = bot.clicker
        for n in range(3):
            c.rect = screen.client_rect(c.hwnd)
            sp = screen.project(c.cam.read(), st_pos, c.rect)
            if sp and c._safe(*sp) and screen.u32.GetForegroundWindow() == c.hwnd:
                screen.click(*sp, hold=0.08)
            time.sleep(2.5)
            if active_tab() is not None:
                break
            log(f"  메뉴 안 열림({n + 1}번째 좌클릭, 역 화면 위치 {sp})")
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
        if LIST:                                # 역 목록 칸 순서 확인: 한 칸씩 내리며 사진, 고르지 않고 닫음
            shot("list_00")
            for k in range(1, 22):
                pad.tap("DPAD_DOWN")
                time.sleep(0.5)
                shot(f"list_{k:02d}")
            for _ in range(4):
                pad.tap("B")
                time.sleep(0.5)
            return True
        # 0.4초 간격 십자키는 절반쯤 씹힘(10-23: 6번 눌러 3칸) → 누를 때마다 목록 화면이 바뀌었는지 보고 셈
        def pane():
            from PIL import ImageGrab
            x, y, w, h = screen.client_rect(bot.clicker.hwnd)
            return ImageGrab.grab(bbox=(x + int(w * 0.57), y + int(h * 0.18), x + int(w * 0.96), y + int(h * 0.9))).convert("L").resize((96, 120))
        moved = presses = 0
        while moved < abs(downs) and presses < abs(downs) * 3:
            a = pane()
            pad.tap("DPAD_DOWN" if downs > 0 else "DPAD_UP", hold=0.12)
            time.sleep(0.7)
            b = pane()
            presses += 1
            diff = sum(abs(p - q) for p, q in zip(a.getdata(), b.getdata())) / (96 * 120)
            if diff > 2.0:
                moved += 1
        log(f"  목록 {moved}/{abs(downs)}칸 이동(누름 {presses}번)")
        shot("pick")
        if moved != abs(downs):
            log("  목록 칸 이동 실패: 선택하지 않고 닫음")
            for _ in range(4):
                pad.tap("B")
                time.sleep(0.5)
            return False
        pad.tap("A")
        time.sleep(1.2)
        pad.tap("A")
        time.sleep(12)
        bot.r.scan()
        nav.mesh_t = 0                         # 새 곳 지도 바로 다시 읽기
        nav.prev = None
        return True

    def probe_interact(st_pos):
        """역 앞에서 어떤 입력이 메뉴를 여는지 하나씩 시험(10-23: 우클릭+A로 안 열림). 열리면 B로 닫고 다음."""
        pad.stick(0, 0)
        time.sleep(1.0)
        c = bot.clicker
        c.rect = screen.client_rect(c.hwnd)
        sp = screen.project(c.cam.read(), st_pos, c.rect)
        log(f"  역 화면 위치 {sp}, 클릭 허용 {bool(sp and c._safe(*sp))}, 게임 창 앞 {screen.u32.GetForegroundWindow() == c.hwnd}")

        def lclick():
            if sp and c._safe(*sp):
                screen.click(*sp, hold=0.08)
                return True
            return False
        tests = [("A 짧게", lambda: pad.tap("A")), ("A 0.6초", lambda: pad.tap("A", hold=0.6)),
                 ("우클릭", lambda: c.rclick_world(st_pos)), ("좌클릭", lclick),
                 ("우클릭 뒤 1초 A", lambda: (c.rclick_world(st_pos), time.sleep(1.0), pad.tap("A")))]
        for name, fn in tests:
            r = fn()
            time.sleep(2.5)
            k = active_tab()
            shot("probe_" + name.replace(" ", ""))
            log(f"  [{name}] 반환 {r} → 메뉴 {TABS[k] if k is not None else '안 열림'}")
            if k is not None:
                for _ in range(2):
                    pad.tap("B")
                    time.sleep(0.6)
            time.sleep(1.0)

    def quest_state():
        out = {}
        for q in instances("LiveQuest"):
            try:
                pr = ue.oprops(q)
                qid = ue.fstring(q + pr["ID"].offset) if pr["ID"].kind == "StrProperty" else ue.fname(q + pr["ID"].offset)
                if qid in ("CA05", "CA07", "CA04"):
                    sp_ = pr["State"]
                    inner = ue.props(sp_.struct)["State"].offset
                    out[qid] = ue.read(q + sp_.offset + inner, 1).hex()
            except Exception:
                continue
        try:
            runner = next(o for o in instances("BP_QuestRunner_C") if not ue.objname(o).startswith("Default__"))
            pr = ue.oprops(runner)
            fq = ue.q(runner + pr["FocusedQuest"].offset)
            out["추적"] = ue.objname(fq) if fq else "없음"
        except Exception as e:
            out["추적"] = f"읽기 실패 {str(e)[:40]}"
        return out

    def quest_meet():
        """도착한 곳 근처 퀘스트 NPC를 적고, CA05 주민(없으면 가장 가까운 퀘스트 NPC)에게 걸어가 좌클릭 → A로 대화 넘김."""
        log("  퀘스트 상태(전):", quest_state())
        time.sleep(3)
        bot.r.scan()
        me = bot.r.loc(bot.r.player)
        cands = []
        for o, n in bot.r.quest_objs.items():
            try:
                p = bot.r.loc(o)
                cands.append((math.dist(p[:2], me[:2]), ue.objname(o), n, p, o))
            except Exception:
                continue
        cands.sort(key=lambda c: c[0])
        log(f"  근처 퀘스트 대상 {len(cands)}개(가까운 순):")
        for d, on, n, p, _ in cands[:20]:
            log(f"    {d:6.0f} {n} {on[:70]} {tuple(round(v) for v in p)}")
        pick = next((c for c in cands if "CA05" in c[1] and "Giver" in c[1]), None) if not GOTO else None
        pick = pick or next((c for c in cands if "CA05" in c[1]), None)
        if not pick:
            log("  CA05 대상 없음 → 말 걸기 안 함")
            shot("no_ca05")
            return
        d, on, n, p, o = pick
        log(f"  고른 대상: {on} 거리 {d:.0f}")
        res, sec = walk(p, 60 + d / 250)
        log(f"  대상까지 걷기 {res} {sec:.0f}초")
        shot("near_npc")
        c = bot.clicker
        c.rect = screen.client_rect(c.hwnd)
        p2 = bot.r.loc(o)
        sp_ = screen.project(c.cam.read(), (p2[0], p2[1], p2[2] + 60), c.rect)
        if sp_ and c._safe(*sp_) and screen.u32.GetForegroundWindow() == c.hwnd:
            screen.click(*sp_, hold=0.08)
        log(f"  NPC 좌클릭 {sp_}")
        time.sleep(2.5)
        shot("talk_00")
        for k in range(1, 9):
            pad.tap("A")
            time.sleep(1.6)
            shot(f"talk_{k:02d}")
        log("  퀘스트 상태(후):", quest_state())

    def task_states():
        out = {}
        for cls in ("ExploreTask", "InteractTask"):
            for t in instances(cls):
                try:
                    pr = ue.oprops(t)
                    tid = ue.fstring(t + pr["ID"].offset) if pr["ID"].kind == "StrProperty" else ue.fname(t + pr["ID"].offset)
                    if tid in ("CA05_E20", "CA05_I18", "CA05_E01", "CA05_I01"):
                        sp_ = pr["State"]
                        out[tid] = ue.read(t + sp_.offset + ue.props(sp_.struct)["State"].offset, 1).hex()
                except Exception:
                    continue
        return out

    def fresh_guide(me):
        """내 600 안에서 시작하는 안내선 중 가장 짧은 것. 옛 안내선(10-24: 마을행 141k)이 남아 있어도 지금 목표 쪽만 고름."""
        best, best_len = None, 1e18
        for g in bot.r.guides:
            try:
                sp = ue.q(g + bot.r._off(g, "SplineComponent"))
                pts = bot.r.spline(sp) if sp else []
            except Exception:
                continue
            if len(pts) < 2 or math.dist(pts[0][:2], me[:2]) > 600:
                continue
            ln = sum(math.dist(a[:2], b[:2]) for a, b in zip(pts, pts[1:]))
            if ln < best_len:
                best, best_len = pts, ln
        if best:
            return best, "guide"
        return bot.r.guide_path(me[:2], press_xy=me[:2])

    gates_cache = {"t": 0.0, "list": []}

    def gates_near(me, radius=2500):
        """이름에 Gate가 들어간 문 액터(장치 Gimmick 제외) 위치. 30초마다 다시 훑음."""
        if time.time() - gates_cache["t"] > 30:
            gates_cache["t"] = time.time()
            out, t0 = [], time.time()
            for o in ue.iter_objects():
                if time.time() - t0 > 6:
                    break
                try:
                    c = ue.clsname(o)
                    if "Gate" in c and "Gimmick" not in c and not ue.objname(o).startswith("Default__"):
                        out.append((bot.r.loc(o), bot.r.yaw(o)))
                except Exception:
                    continue
            gates_cache["list"] = out
        return [g for g in gates_cache["list"] if math.dist(g[0][:2], me[:2]) < radius]

    def via_gate(me, q):
        """me→q 직선이 문 액터 500 안을 지나면 문 앞 → 문 가운데 → 문 너머 점을 끼워 넣음(10-24 DesertGate 앞에서 30초씩 반복)."""
        dx, dy = q[0] - me[0], q[1] - me[1]
        L = math.hypot(dx, dy) or 1.0
        ux, uy = dx / L, dy / L
        for g, yaw in gates_near(me):
            t = ((g[0] - me[0]) * ux + (g[1] - me[1]) * uy)
            if not (-200 < t < L + 200):
                continue
            off = abs((g[0] - me[0]) * uy - (g[1] - me[1]) * ux)
            if off < 700:
                # 문 구멍 방향 = 문 액터의 앞(yaw)축. 진행 방향(대각선)으로 잡으면 문틀을 찍음(10-24: 기둥 위로 올라감)
                fx, fy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
                if fx * ux + fy * uy < 0:
                    fx, fy = -fx, -fy
                return [(g[0] - fx * 450, g[1] - fy * 450, g[2]), (g[0], g[1], g[2]), (g[0] + fx * 550, g[1] + fy * 550, g[2])]
        return []

    stuck_n = [0]
    DEATH_SPOT = (14300, 98200, 200)   # 10-25 두 번 연속 한 번에 죽은 자리

    def survey_volumes(me, radius=4500):
        """빠지면 죽는 곳 찾기: 이름·클래스에 Volume/Kill/Death/Pain/Water/Ocean/Fall이 든 액터의 위치·크기·관련 속성."""
        keys = ("volume", "kill", "death", "pain", "water", "ocean", "fall", "void", "drown", "damage")
        rows, t0 = [], time.time()
        for o in ue.iter_objects():
            if time.time() - t0 > 40:
                break
            try:
                c = ue.clsname(o)
                n = ue.objname(o)
                low = (c + " " + n).lower()
                if not any(k in low for k in keys) or n.startswith("Default__") or "SpawnVolume" in c:
                    continue
                p = bot.r.loc(o)
                d = math.dist(p[:2], me[:2])
                if d > radius:
                    continue
                info = ""
                try:
                    rc = ue.q(o + bot.r._off(o, "RootComponent"))
                    sc = struct.unpack("<ddd", ue.read(rc + bot.r._off(rc, "RelativeScale3D"), 24))
                    info += f" 크기{tuple(round(v, 1) for v in sc)}"
                except Exception:
                    pass
                pr = ue.oprops(o)
                for k in ("bPainCausing", "DamagePerSec", "bWaterVolume", "KillZ", "bEntryPain"):
                    if k in pr:
                        q = pr[k]
                        v = ue.f32(o + q.offset) if q.kind == "FloatProperty" else ue.read(o + q.offset, 1).hex()
                        info += f" {k}={v}"
                rows.append((d, c, n, p, info))
            except Exception:
                continue
        rows.sort(key=lambda x: x[0])
        log(f"  [조사] 죽은 자리 근처 구역 {len(rows)}개 (내 위치 {tuple(round(v) for v in me)}):")
        for d, c, n, p, info in rows[:40]:
            log(f"    {d:6.0f} {c} {n[:60]} {tuple(round(v) for v in p)}{info}")
        shot("deathzone_survey")
    hpwatch = {"hist": [], "shot": 0.0, "pot": 0.0}

    def survive():
        """안내선 직접 따라가기에도 생존 처리(10-25: 7초에 104→4.7 깎이고 물약 없이 걷다 사망).
        체력 기록 → 3초에 30% 넘게 깎이면 사진 + 원인 조사용 주변 몹 기록, 40% 아래면 물약(30초 쿨). 죽었으면 True."""
        try:
            hp, hpm = bot.r.hp(bot.r.player)
        except Exception:
            return False
        if hp is None:
            return False
        now = time.time()
        if hp <= 0:
            if now - hpwatch.get("dshot", 0) > 20:
                hpwatch["dshot"] = now
                log(f"  [사망] 위치 {tuple(round(v) for v in bot.r.loc(bot.r.player))}")
                shot("died")
            return True
        if not hpwatch.get("surveyed"):
            me = bot.r.loc(bot.r.player)
            if math.dist(me[:2], DEATH_SPOT[:2]) < 2500:   # 두 번 죽은 자리 근처: 멈춰서 주변 구역 조사 한 번
                hpwatch["surveyed"] = True
                pad.stick(0, 0)
                survey_volumes(me)
        h = hpwatch["hist"]
        h.append((now, hp))
        while h and now - h[0][0] > 3:
            h.pop(0)
        if hpm and h and h[0][1] - hp > 0.3 * hpm and now - hpwatch["shot"] > 10:
            hpwatch["shot"] = now
            me = bot.r.loc(bot.r.player)
            near = []
            for o, n in list(bot.r.mobs.items()):
                try:
                    p = bot.r.loc(o)
                    d = math.dist(p[:2], me[:2])
                    if d < 2500:
                        near.append((round(d), n))
                except Exception:
                    continue
            log(f"  [피해] 3초에 {h[0][1]:.0f}→{hp:.0f}, 위치 {tuple(round(v) for v in me)}, 주변 몹 {sorted(near)[:8]}")
            shot("bigdamage")
        # 크리퍼(자폭)가 450 안이면 반대쪽으로 1.2초 달리고 구르기(10-25: 크리퍼 3마리 옆에서 104→53, 이어 사망)
        try:
            me = bot.r.loc(bot.r.player)
            for o, n in list(bot.r.mobs.items()):
                if "Creeper" not in n:
                    continue
                cp = bot.r.loc(o)
                if math.dist(cp[:2], me[:2]) < 450 and now - hpwatch.get("flee", 0) > 1.5:
                    hpwatch["flee"] = now
                    dx, dy = me[0] - cp[0], me[1] - cp[1]
                    log(f"  [회피] 크리퍼 {math.dist(cp[:2], me[:2]):.0f} → 반대로 피함")
                    pad.stick(*bot.to_stick(dx, dy))
                    pad.tap("LEFT_SHOULDER")   # 구르기(LB)
                    time.sleep(1.2)
                    pad.stick(0, 0)
                    break
        except Exception:
            pass
        if hpm and hp / hpm < 0.4 and now - hpwatch["pot"] > 30 and \
                (bot.r.attr(bot.r.player, "ATR_Health", "HealthPotionCharges") or 0) >= 1:
            pad.trigger(left=True)
            hpwatch["pot"] = now
            log(f"  [생존] 물약 (체력 {hp:.0f}/{hpm:.0f})")
        return False

    def away_from_npcs(tgt, me):
        """클릭할 곳 200 안에 NPC(상인 등)가 있으면 이동 방향 옆으로 250 비켜 찍음(NPC 클릭 = 대화·상점 열림)."""
        try:
            npcs = [bot.r.loc(o) for o in list(bot.r.npcs) + list(bot.r.quest_objs)]
        except Exception:
            return tgt
        for n in npcs:
            if math.dist(n[:2], tgt[:2]) < 200:
                dx, dy = tgt[0] - me[0], tgt[1] - me[1]
                L = math.hypot(dx, dy) or 1.0
                side = 1 if (n[0] - me[0]) * (-dy) + (n[1] - me[1]) * dx < 0 else -1   # NPC 반대쪽으로
                return (tgt[0] - dy / L * 250 * side, tgt[1] + dx / L * 250 * side, tgt[2])
        return tgt

    def stick_through(points, per_point=6.0):
        """패드 스틱으로 점들을 차례로 걸어감(클릭은 화면에서 가장 위의 면 = 문 지붕·기둥 꼭대기를 목적지로 잡음, 10-25)."""
        for q in points:
            ts = time.time()
            while time.time() - ts < per_point and time.time() < run_deadline:
                modal_guard()
                if survive():
                    pad.stick(0, 0)
                    return "died"
                me = bot.r.loc(bot.r.player)
                if math.dist(me[:2], q[:2]) < 120:
                    break
                pad.stick(*bot.to_stick(q[0] - me[0], q[1] - me[1]))
                time.sleep(0.1)
        pad.stick(0, 0)
        me = bot.r.loc(bot.r.player)
        return "arrived" if math.dist(me[:2], points[-1][:2]) < 300 else "partial"

    def walk_guide(pts, j0, dist_limit):
        """안내선 점을 차례로 클릭(점당 최대 8초, 150 안이면 다음 점). 2초 동안 100도 못 움직이면 점프 한 번."""
        t0 = time.time()
        acc = 0.0
        prev = pts[j0]
        seq = []
        here = bot.r.loc(bot.r.player)
        for q in pts[j0 + 1:]:
            seq.extend(via_gate(here, q))
            seq.append(q)
            here = q
        if len(seq) > len(pts[j0 + 1:]):
            log(f"      (문 지나기 점 {len(seq) - len(pts[j0 + 1:])}개 끼움)")
        for q in seq:
            acc += math.dist(prev[:2], q[:2])
            prev = q
            ts, last_p, last_t = time.time(), bot.r.loc(bot.r.player), time.time()
            while time.time() - ts < 8 and time.time() < run_deadline:
                modal_guard()
                if survive():
                    return "died", time.time() - t0
                me = bot.r.loc(bot.r.player)
                if math.dist(me[:2], q[:2]) < 150:
                    break
                tgt = q if math.dist(me[:2], q[:2]) < 900 else tuple(me[i] + (q[i] - me[i]) * 900 / math.dist(me[:2], q[:2]) for i in range(3))
                tgt = away_from_npcs(tgt, me)
                if not bot.clicker.click_world(tgt, me):
                    pad.stick(*bot.to_stick(q[0] - me[0], q[1] - me[1]))
                if time.time() - last_t > 2:
                    if math.dist(me[:2], last_p[:2]) < 100:
                        # 상점 등 창이 열렸을 수 있음(10-24: 문 옆 마을 상인 클릭 → 상점에서 끝까지 멈춤). A는 상점에선 '구매'라
                        # 먼저 B로 닫고, 다음 번에 점프
                        stuck_n[0] += 1
                        near_gate = bool(gates_near(me, 900))   # 문 근처 점프는 기둥 위로 올라가게 함 → B만
                        pad.tap("B" if (near_gate or stuck_n[0] % 2) else "A")
                    last_p, last_t = me, time.time()
                time.sleep(0.1)
            pad.stick(0, 0)
            if acc >= dist_limit:
                break
        me = bot.r.loc(bot.r.player)
        return ("arrived" if math.dist(me[:2], prev[:2]) < 300 else "partial"), time.time() - t0

    def follow():
        """휠 클릭 → 게임 안내 경로(GCN_ShowGuidance) 읽기 → 경로 따라 2500 앞 점까지 걷기 → 반복."""
        log("  퀘스트:", quest_state(), task_states())
        misses = 0
        k = 0
        while time.time() < run_deadline - 20:
            k += 1
            me = bot.r.loc(bot.r.player)
            modal_guard()
            if screen.u32.GetForegroundWindow() == bot.clicker.hwnd:
                pad.tap("LEFT_THUMB", hold=0.15)   # 안내선 = 패드 L3(10-24 확인, 휠 클릭은 안 먹힘)
            time.sleep(1.5)
            bot.r.scan()
            pts, kind = fresh_guide(me)
            if not pts:
                misses += 1
                log(f"  [{k}] 안내선 없음({misses}번째) 위치 {tuple(round(v) for v in me)}")
                shot("noguide")
                if misses >= 4:
                    break
                time.sleep(3)
                continue
            misses = 0
            # 안내선 첫 점(예전에 휠을 누른 자리)부터 재면 이미 지난 곳이 목표가 됨(10-24: 같은 자리 '도착' 158번)
            # → 내 위치에서 가장 가까운 점부터 2500 앞. 그래도 400 안이면 다음 점들로 더 밀어냄.
            j0 = min(range(len(pts)), key=lambda j: math.dist(pts[j][:2], me[:2]))
            acc, tgt = 0.0, pts[-1]
            for a, b in zip(pts[j0:], pts[j0 + 1:]):
                acc += math.dist(a[:2], b[:2])
                if acc >= 2500 and math.dist(b[:2], me[:2]) > 400:
                    tgt = b
                    break
            total = sum(math.dist(a[:2], b[:2]) for a, b in zip(pts, pts[1:]))
            log(f"  [{k}] 안내선 {kind} {len(pts)}점 길이 {total:.0f}, 끝 {tuple(round(v) for v in pts[-1])} → 목표 {tuple(round(v) for v in tgt)}")
            g_near = gates_near(me, 1200)
            if g_near and me[2] > g_near[0][0][2] + 80:
                g, yaw = g_near[0]
                fx, fy = math.cos(math.radians(yaw)), math.sin(math.radians(yaw))
                if fx * (tgt[0] - me[0]) + fy * (tgt[1] - me[1]) < 0:
                    fx, fy = -fx, -fy
                log(f"      (문 옆 높은 곳 z{me[2]:.0f} → 스틱으로 내려오기)")
                stick_through([(me[0] + fx * 700, me[1] + fy * 700, g[2])], per_point=5)
                me = bot.r.loc(bot.r.player)
            gp = via_gate(me, tgt)
            if gp:
                # 문을 끼고 가는 구간은 내 길찾기(점프 연결로 문 옆 기둥 위에 올라감, 10-25 두 번) 대신 문 축 세 점을 직접 찍음
                log(f"      (문 통과: {[tuple(round(v) for v in q) for q in gp]})")
                t_g = time.time()
                r0, s0 = walk(gp[0], 45)   # 문 앞까지는 길찾기로 돌아감(10-25: 문 동쪽에서 직선이 노점·울타리에 막혀 100초씩)
                r1 = stick_through(gp[1:])  # 문 안쪽은 스틱으로(클릭하면 기둥 위로 올라감)
                res, sec = r1, time.time() - t_g
                log(f"      (문 앞까지 {r0}, 스틱 통과 {r1})")
            else:
                res, sec = walk(tgt, 30 + min(acc, total) / 200)
            if res in ("failed", "timeout"):
                # 내 길찾기 지도가 끊긴 곳(10-24: 열린 문간에서 출발점이 지도 밖) → 게임이 계산한 안내선 점을 직접 클릭해 따라감
                res, sec = walk_guide(pts, j0, 2500)
                log(f"      (안내선 직접 따라가기 {res})")
            me2 = bot.r.loc(bot.r.player)
            log(f"      걷기 {res} {sec:.0f}초, 위치 {tuple(round(v) for v in me2)} | {quest_state()} {task_states()}")
            if k % 3 == 0 or res != "arrived":
                shot(f"follow_{k:02d}_{res}")
            if res == "died":
                time.sleep(8)
                pad.tap("A")
                time.sleep(10)

    def goto_station(target):
        """가장 가까운 아는 역까지 걸어가서 목록 칸 차이만큼 빠른 이동. 도착은 좌표로 확인."""
        me = bot.r.loc(bot.r.player)
        order = sorted(STATIONS, key=lambda n: math.dist(STATIONS[n][1][:2], me[:2]))
        if order[0] == target and math.dist(STATIONS[target][1][:2], me[:2]) < 3000:
            log(f"  이미 {target} 근처")
            return True
        S = stations()
        # 가장 가까운 역이 못 가는 곳일 수 있음(10-24: 허니브룩 다리 역이 올라간 다리 건너편) → 가까운 순으로 3곳까지
        for here in order[:3]:
            if here == target:
                continue
            sp = min(S.values(), key=lambda p: math.dist(p[:2], STATIONS[here][1][:2])) if S else STATIONS[here][1]
            me = bot.r.loc(bot.r.player)
            d0 = math.dist(me[:2], sp[:2])
            res, sec = walk(sp, 40 + d0 / 250)
            log(f"  역 {here}까지 걷기 {res} {sec:.0f}초({d0:.0f})")
            if res == "arrived":
                break
            shot("goto_walkfail")
        else:
            return False
        downs = STATIONS[target][0] - STATIONS[here][0]
        if not travel(sp, downs):
            return False
        me2 = bot.r.loc(bot.r.player)
        d = math.dist(me2[:2], STATIONS[target][1][:2])
        log(f"  빠른 이동 {here} → {target} ({downs:+d}칸): 도착 위치 {tuple(round(v) for v in me2)}, 목표 역까지 {d:.0f}")
        shot("goto_arrived")
        return d < 3000

    def survey_names(key="CA05", radius=12000):
        """도착한 곳에서 이름에 key가 들어간 액터를 위치와 함께 적음(퀘스트 목표 지점 찾기)."""
        me = bot.r.loc(bot.r.player)
        rows, t0 = [], time.time()
        for o in ue.iter_objects():
            if time.time() - t0 > 60:
                break
            try:
                n = ue.objname(o)
                if key not in n or n.startswith("Default__"):
                    continue
                p = bot.r.loc(o)
                rows.append((math.dist(p[:2], me[:2]), ue.clsname(o), n, p))
            except Exception:
                continue
        rows.sort()
        log(f"  이름에 {key} 들어간 위치 있는 객체 {len(rows)}개:")
        for d, c, n, p in rows[:40]:
            log(f"    {d:7.0f} {c} {n[:70]} {tuple(round(v) for v in p)}")

    t0, tries = time.time(), []
    run_deadline = t0 + SECONDS
    if "guideinfo" in sys.argv[2:]:   # 조사: 휠 클릭 → 안내선 끝(지금 퀘스트 목표)과 길이, 가까운 역만 적음. 이동 없음.
        log("  퀘스트:", quest_state(), task_states())
        def mid_center():
            x, y, w, h = screen.client_rect(bot.clicker.hwnd)
            screen.u32.SetCursorPos(x + w // 2, y + int(h * 0.45))
            time.sleep(0.2)
            screen.u32.mouse_event(0x0020, 0, 0, 0, 0)
            time.sleep(0.1)
            screen.u32.mouse_event(0x0040, 0, 0, 0, 0)
        ways = [("패드 L3", lambda: pad.tap("LEFT_THUMB", hold=0.15)), ("휠 클릭(화면 가운데)", mid_center),
                ("패드 L3 길게", lambda: pad.tap("LEFT_THUMB", hold=0.6)), ("휠 클릭 다시", mid_center)]
        for k, (wname, press) in enumerate(ways):
            modal_t["t"] = 0.0
            modal_guard()
            me = bot.r.loc(bot.r.player)
            if screen.u32.GetForegroundWindow() == bot.clicker.hwnd:
                press()
            log(f"  시도 {k + 1}: {wname}")
            time.sleep(2.5)
            bot.r.scan()
            pts, kind = bot.r.guide_path(me[:2], press_xy=me[:2])
            if pts:
                total = sum(math.dist(a[:2], b[:2]) for a, b in zip(pts, pts[1:]))
                end = pts[-1]
                log(f"  안내선 {kind} {len(pts)}점, 길이 {total:.0f}, 시작 {tuple(round(v) for v in pts[0])}, 끝 {tuple(round(v) for v in end)}")
                log("  점들:", [tuple(round(v) for v in p) for p in pts[::max(1, len(pts) // 12)]])
                for n in sorted(STATIONS, key=lambda n: math.dist(STATIONS[n][1][:2], end[:2]))[:3]:
                    log(f"    끝에서 역 {n}까지 {math.dist(STATIONS[n][1][:2], end[:2]):.0f}")
                shot("guideinfo")
                break
            log(f"  안내선 없음({k + 1}번째)")
            shot(f"noguide_{k}")
        pad.reset()
        bot.stop = True
        return
    if GOTO:
        ok = goto_station(GOTO)
        log(f"[결과] {GOTO} 빠른 이동 {'성공' if ok else '실패'}")
        time.sleep(4)
        bot.r.scan()
        survey_names("CA05")
        log("  퀘스트:", quest_state(), task_states())
        if "talk" in sys.argv[2:]:   # 진행 중 상호작용 단계 시험: 가장 가까운 CA05 NPC에게 걸어가 좌클릭
            quest_meet()
            time.sleep(2)
            log("  퀘스트(말 건 뒤):", quest_state(), task_states())
        nav.save()
        pad.reset()
        bot.stop = True
        return
    if FOLLOW:
        follow()
        nav.save()
        pad.reset()
        bot.stop = True
        log(f"\n[결과] 안내선 따라가기 끝, 걷기 통계 {nav.stats}")
        return
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
        if PROBE:
            probe_interact(sp)
            break
        if not travel(sp, downs):
            rec["travel_error"] = "지도 탭 확인 실패"
            tries.append(rec)
            break
        if LIST:
            log("  역 목록 사진 찍음")
            break
        if QUEST:
            me2 = bot.r.loc(bot.r.player)
            log(f"  빠른 이동 뒤 위치 {tuple(round(v) for v in me2)}, 웅덩이 연못 역까지 {math.dist(me2[:2], OASIS[:2]):.0f}")
            shot("arrived")
            quest_meet()
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
    import faulthandler
    _hang = open(os.path.join(HERE, "tnav_hang.txt"), "w", encoding="utf-8")
    faulthandler.dump_traceback_later(120, repeat=True, file=_hang)   # 2분마다 지금 도는 줄을 적음(멈춘 곳 찾기)
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
                for f in sorted(shots, key=os.path.getmtime)[-30:]:
                    z.write(f, os.path.basename(f))
            for f in shots:
                os.remove(f)
    except Exception as e:
        print("사진 묶기 실패", e)
    print("\n결과를 저장했어:", OUT)
