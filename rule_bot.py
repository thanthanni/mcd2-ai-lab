"""마던2 규칙 봇 v1 (초보 수준 목표). 게임은 읽기만 하고, 조작은 가상 패드로만 한다.

판단(초당 약 15번):
  - 체력 40% 아래 + 물약 있음 → LT(물약)
  - 체력 30% 아래(몹 4마리 넘게 몰리면 50%) + 몹이 가까움 → 몹 무리 반대쪽으로 구르고 2초 물러남
  - 몹 4마리 넘게 몰리면 물약도 60%에서 마심
  - 가까운 적 몹이 2마리 넘게 붙어 있고 영혼 충분 → 유물(B, RB)을 번갈아(각 12초 간격)
  - 가장 가까운 적이 근접 거리 안 → X 연타, 멀면 그쪽으로 걷기(1.5초 넘게 안 움직이면 점프)
  - 1.5초 때려도 체력이 안 줄면 그 몹은 20초 무시(죽은 몸·무적 상태)
  - 3초 쫓아가도 내가 제자리면(높은 곳·벽 너머 몹) 그 몹은 25초 무시
  - 가까운 적이 없으면 멀리(6000까지) 있는 적한테 걸어감
  - 그것도 없으면 길 안내선(왼쪽 스틱 누르기)을 켜고 그 경로를 따라감, 경로가 없으면 돌아다님
처음에 스틱 방향을 맞추려고 오른쪽·위로 0.6초씩 걸어 본다(넓은 곳에서 시작).
진짜 패드가 꽂혀 있으면 뺄 때까지 기다리고, 게임 창은 자동으로 앞으로 가져온다. 오프라인 사본 캐릭터로만. 멈추려면 이 창에서 Ctrl+C.
"""
from __future__ import annotations

import json
import math
import os
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from state_probe import find_ohs_app  # noqa: E402
from state_reader import Reader       # noqa: E402

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 120.0
OUT = os.path.join(HERE, "bot_result.txt")
LOG = os.path.join(HERE, "bot_log.jsonl")
CALIB = os.path.join(HERE, "calib.json")

PASSIVE = ("Frog", "Sheep", "Cow", "Pig", "Chicken", "Villager", "Wolf", "Cat", "Rabbit", "Horse",
           "Llama", "Fox", "Bee", "Turtle", "Parrot", "Goat", "Axolotl", "Camel", "Armadillo", "Allay",
           "Squid", "Dolphin", "Mooshroom", "Ocelot", "Panda", "Sniffer", "Strider", "Donkey", "Mule",
           "TargetDummy", "Dummy")   # 동물·허수아비는 안 때림
MELEE = 230          # 이 거리 안이면 때림(게임 근접 사거리 300)
SIGHT = 1300         # 싸울 상대로 보는 거리(벽 너머 몹은 화면에 그려졌는지로 따로 거름)
SEEK = 6000          # 싸울 상대가 없을 때 찾아가는 거리
ZGAP = 250           # 높이 차가 이보다 크면 다른 층으로 봄
lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


class Pad:
    def __init__(self):
        import vgamepad as vg
        self.vg = vg
        self.p = vg.VX360Gamepad()
        self.B = vg.XUSB_BUTTON

    def stick(self, x, y):
        self.p.left_joystick_float(max(-1, min(1, x)), max(-1, min(1, y)))
        self.p.update()

    def tap(self, name, hold=0.08):
        b = getattr(self.B, "XUSB_GAMEPAD_" + name)
        self.p.press_button(b)
        self.p.update()
        time.sleep(hold)
        self.p.release_button(b)
        self.p.update()

    def trigger(self, left: bool, hold=0.1):
        (self.p.left_trigger_float if left else self.p.right_trigger_float)(1.0)
        self.p.update()
        time.sleep(hold)
        (self.p.left_trigger_float if left else self.p.right_trigger_float)(0.0)
        self.p.update()

    def reset(self):
        self.p.reset()
        self.p.update()


def now_ok(bot):
    return time.time() >= bot.click_off_until


class Bot:
    def __init__(self, ue, pad):
        self.ue, self.pad = ue, pad
        self.r = Reader(ue)
        self.r.scan()
        self.lock = threading.Lock()
        self.stop = False
        self.inv = None               # 세계 방향 → 스틱 방향 2x2
        self.last_art = {"B": 0.0, "RIGHT_SHOULDER": 0.0}
        self.last_roll = self.last_potion = 0.0
        self.stuck_since = None
        self.last_pos = None
        self.seen = {}                # 몹 → (마지막 체력, 최대, 거리)
        self.ignore = {}              # 몹 → 무시 끝나는 시각
        self.hit = None               # (몹, 때리기 시작한 시각, 그때 체력)
        self.wander = (1.0, 0.0)      # 돌아다닐 세계 방향
        self.wander_until = 0.0
        self.last_guide = 0.0
        self.retreat_until = 0.0
        self.chase = None             # (쫓은 몹들, 시작 시각, 그때 가장 가까웠던 거리)
        self.press_xy = None          # 마지막으로 왼쪽 스틱을 누른 위치
        self.cur_path, self.cur_i = None, 0
        self.last_arrive = 0.0
        self.clicker = None           # screen.Clicker(클릭 이동), main에서 켬
        self.click_off_until = 0.0    # 막혀서 잠깐 스틱으로 바꾼 동안
        self.moved_by = ""
        self.last_guide_ok = 0.0      # 마지막으로 안내 경로를 따라간 시각
        self.tried = {}               # 퀘스트 대상 → 마지막으로 상호작용해 본 시각
        self.last_track = 0.0         # 마지막으로 퀘스트 추적 버튼을 누른 시각
        self.wp_best = None           # (경로 점, 가장 가까웠던 거리, 그때 시각)
        self.detour_until = 0.0
        self.detour = (0.0, 0.0)
        self.skip = set()             # 막혀서 건너뛴 경로 점
        self.stats = {"kills": 0, "potions": 0, "rolls": 0, "artifacts": 0, "jumps": 0,
                      "melee": 0, "deaths": 0, "dmg_taken": 0.0}
        threading.Thread(target=self._rescan, daemon=True).start()

    def _rescan(self):
        while not self.stop:
            time.sleep(3)
            try:
                fresh = Reader(self.ue)
                fresh.chain, fresh.off = self.r.chain, self.r.off
                fresh.scan()
                with self.lock:
                    self.r.player = fresh.player or self.r.player
                    self.r.mobs, self.r.atr = fresh.mobs, fresh.atr
                    self.r.navpaths, self.r.trail, self.r.guides = fresh.navpaths, fresh.trail, fresh.guides
                    self.r.quest_objs = fresh.quest_objs
            except Exception:
                pass

    # 스틱 맞추기 ---------------------------------------------------------
    def calibrate(self):
        if os.path.exists(CALIB):
            self.inv = json.load(open(CALIB))["inv"]
            log("스틱 방향: 저장된 값 사용(calib.json 지우면 다시 맞춤)")
            return
        cols = []
        for sx, sy in ((1, 0), (0, 1)):
            p0 = self.r.loc(self.r.player)
            self.pad.stick(sx, sy)
            time.sleep(0.6)
            p1 = self.r.loc(self.r.player)
            self.pad.stick(0, 0)
            time.sleep(0.4)
            dx, dy = p1[0] - p0[0], p1[1] - p0[1]
            n = math.hypot(dx, dy)
            if n < 50:
                raise RuntimeError("스틱 맞추기 중에 캐릭터가 거의 안 움직였어. 진짜 패드를 뺐는지, 넓은 곳인지 확인해 줘.")
            cols.append((dx / n, dy / n))
        (a, c), (b, d) = cols          # M = [[a b],[c d]]: 스틱 → 세계
        det = a * d - b * c
        self.inv = [[d / det, -b / det], [-c / det, a / det]]
        json.dump({"inv": self.inv, "cols": cols}, open(CALIB, "w"))
        log(f"스틱 방향 맞춤: 오른쪽={tuple(round(v, 2) for v in cols[0])} 위={tuple(round(v, 2) for v in cols[1])}")

    def to_stick(self, dx, dy, mag=1.0):
        (p, q), (s, t) = self.inv
        x, y = p * dx + q * dy, s * dx + t * dy
        n = math.hypot(x, y) or 1
        return x / n * mag, y / n * mag

    # 판단 ----------------------------------------------------------------
    def step(self):
        r, now = self.r, time.time()
        with self.lock:
            me = r.player
            mobs = dict(r.mobs)
        x, y, z = r.loc(me)
        hp, hpmax = r.hp(me)
        soul = r.attr(me, "ATR_Soul", "Souls") or 0
        potions = r.attr(me, "ATR_Health", "HealthPotionCharges") or 0
        if hp is None or not hpmax:
            return {"skip": "hp"}
        if hp <= 0:
            self.pad.reset()
            return {"dead": True}

        foes, far = [], []
        for o, n in mobs.items():
            if any(k in n for k in PASSIVE) or self.ignore.get(o, 0) > now:
                continue
            try:
                mx, my, mz = r.loc(o)
                h, m = r.hp(o)
            except Exception:
                continue
            d = math.hypot(mx - x, my - y)
            if h is None or h <= 0:
                continue
            if d > 350:                      # 벽 너머(붉은 형체)·화면 밖 몹은 무시: 0.5초 넘게 화면에 안 그려짐
                try:
                    if r.render_age(o) > 0.5:
                        self.stats["hidden"] = self.stats.get("hidden", 0) + 1
                        continue
                except Exception:
                    pass
            if d < SIGHT and abs(mz - z) < ZGAP:
                foes.append((d, mx - x, my - y, n, o, h, m))
                self.seen[o] = (h, m, d)
            elif d < SEEK and abs(mz - z) < ZGAP * 2:
                far.append((d, mx - x, my - y, n, o))
        foes.sort(key=lambda f: f[0])
        alive = {f[4] for f in foes}
        for o in list(self.seen):
            if o not in alive:
                h, m, d = self.seen.pop(o)
                if m and h / m < 0.35 and d < 900:
                    self.stats["kills"] += 1

        act = {"hp": round(hp), "soul": round(soul), "foes": len(foes), "pos": [round(x), round(y), round(z)]}
        close = [f for f in foes if f[0] < 500]

        crowd = len([f for f in foes if f[0] < 600])
        if now < self.retreat_until and close:        # 물러나는 중: 몹 반대쪽으로 계속 걷기
            cx = sum(f[1] for f in close) / len(close)
            cy = sum(f[2] for f in close) / len(close)
            self.pad.stick(*self.to_stick(-cx, -cy))
            act["do"] = "retreat"
            return act
        if (hp / hpmax < 0.4 or (crowd >= 4 and hp / hpmax < 0.6)) and potions >= 1 and now - self.last_potion > 2:
            self.pad.trigger(left=True)
            self.last_potion = now
            self.stats["potions"] += 1
            act["do"] = "potion"
            return act
        if (hp / hpmax < 0.3 or (crowd >= 4 and hp / hpmax < 0.5)) and close and now - self.last_roll > 2.6:
            cx = sum(f[1] for f in close) / len(close)
            cy = sum(f[2] for f in close) / len(close)
            self.pad.stick(*self.to_stick(-cx, -cy))
            self.pad.tap("LEFT_SHOULDER")
            self.last_roll = now
            self.retreat_until = now + 2.0          # 굴러서 빠진 뒤 2초 더 물러남
            self.stats["rolls"] += 1
            act["do"] = "roll"
            return act
        if len(close) >= 2 and soul >= 40:
            for b in ("B", "RIGHT_SHOULDER"):
                if now - self.last_art[b] > 12:
                    self.pad.stick(0, 0)
                    self.pad.tap(b)
                    self.last_art[b] = now
                    self.stats["artifacts"] += 1
                    act["do"] = "artifact_" + b
                    return act
        if not foes:
            self.hit = None
            if far and now - self.last_guide_ok > 8:   # 안내 경로가 있으면 먼 몹은 찾아가지 않음
                far.sort()
                d, dx, dy, n, o = far[0]
                act["target"] = f"{n} {round(d)}"
                act["do"] = "seek"
                if self._chase_stuck(o, x, y, now, d):
                    act["do"] = "unreachable"
                    return act
            else:
                if now - self.last_guide > 5:          # 안내선 새로 그리기(누른 위치를 기억해서 새 경로를 알아봄)
                    self.pad.tap("LEFT_THUMB")
                    self.last_guide = now
                    self.press_xy = (x, y)
                path, src = None, None
                try:
                    path, src = r.guide_path((x, y), self.press_xy if now - self.last_guide < 4 else None)
                except Exception:
                    pass
                if now < self.detour_until:        # 막혀서 옆으로 돌아가는 중
                    self.pad.stick(*self.to_stick(*self.detour))
                    act["do"] = "detour"
                    return act
                if path and (not self.cur_path or path[0] != self.cur_path[0] or len(path) != len(self.cur_path)):
                    # 새 경로로 갈아탈 때만 위치를 다시 잡고, 그 뒤로는 점 번호를 앞으로만 진행(왔다 갔다 방지)
                    d0 = [math.hypot(p[0] - x, p[1] - y) for p in path]
                    i = d0.index(min(d0))
                    self.cur_path, self.cur_i = path, min(i + 1, len(path) - 1) if d0[i] < 450 else i
                if self.cur_path:
                    path = self.cur_path
                    def passed(j):   # 점 j에 닿았거나, 이미 다음 구간(j→j+1)으로 넘어간 상태
                        if math.hypot(path[j][0] - x, path[j][1] - y) < 250 or self._key(path[j]) in self.skip:
                            return True
                        nx, ny = path[j + 1][0], path[j + 1][1]
                        return math.hypot(nx - x, ny - y) < math.hypot(nx - path[j][0], ny - path[j][1]) - 50
                    while self.cur_i < len(path) - 1 and passed(self.cur_i):
                        self.cur_i += 1
                    i = self.cur_i
                    di = math.hypot(path[i][0] - x, path[i][1] - y)
                    if i == len(path) - 1 and di < 250:    # 경로 끝(목표) 도착: 상호작용 시도 후 경로 비움
                        self.pad.stick(0, 0)
                        if now - self.last_arrive > 1.5:      # 목표 앞: 공격(X)이 아니라 상호작용(우클릭/A)
                            qa = self._quest_target(x, y, z, now - 1000)   # 90초 규칙 무시하고 가장 가까운 대상
                            ok = False
                            if qa and qa[1] < 600 and self.clicker:
                                ok = self.clicker.rclick_world(qa[2])
                            if not ok:
                                self.pad.tap("A")
                            self.last_arrive = now
                            self.stats["interacts"] = self.stats.get("interacts", 0) + 1
                        self.cur_path = None
                        act["do"] = "arrive"
                        return act
                    dx, dy = path[i][0] - x, path[i][1] - y
                    # 3초 동안 이 점에 100 넘게 못 가까워지면: 옆으로 1.2초 돌아가고, 두 번째면 그 점을 건너뜀
                    k = self._key(path[i])
                    if not self.wp_best or self.wp_best[0] != k or di < self.wp_best[1] - 100:
                        self.wp_best = (k, di, now, self.wp_best[3] if self.wp_best and self.wp_best[0] == k else 0)
                    elif now - self.wp_best[2] > 3:
                        tries = self.wp_best[3] + 1
                        if tries >= 2:
                            self.skip.add(k)
                        side = 1 if tries % 2 else -1
                        self.detour = (-dy * side, dx * side)
                        self.detour_until = now + 1.2
                        self.click_off_until = now + 4
                        self.wp_best = (k, di, now, tries)
                        self.pad.tap("A")
                        self.stats["jumps"] += 1
                        act["do"] = "detour"
                        return act
                    self.last_guide_ok = now
                    act["do"] = "guide"
                    act["wp"] = f"{src or 'keep'} {i}/{len(path)} {round(di)}"
                    self.go(x, y, z, self._ahead(path, i, x, y, z), dx, dy)
                    self._unstick(x, y, now, act)
                    return act
                # 안내선이 10초 넘게 없으면 퀘스트 추적(십자키 오른쪽 길게, PC는 J 길게) → 다음 안내선이 생김
                if now - self.last_guide_ok > 10 and now - self.last_track > 20:
                    self.pad.stick(0, 0)
                    self.pad.tap("DPAD_RIGHT", hold=1.2)
                    time.sleep(0.6)
                    self.pad.tap("LEFT_THUMB")
                    self.last_guide = now
                    self.press_xy = (x, y)
                    self.last_track = now
                    self.stats["track"] = self.stats.get("track", 0) + 1
                    act["do"] = "track_quest"
                    return act
                # 안내선이 없으면(퀘스트 상호작용 구간) 가까운 퀘스트 대상에게 가서 상호작용(우클릭 + A)
                qa = self._quest_target(x, y, z, now)
                if qa:
                    qo, qd, qp = qa
                    act["target"] = f"{r.quest_objs.get(qo, '?')} {round(qd)}"
                    if qd > 230:
                        self.go(x, y, z, qp, qp[0] - x, qp[1] - y)
                        act["do"] = "to_quest"
                    else:
                        self.pad.stick(0, 0)
                        ok = self.clicker.rclick_world(qp) if self.clicker else False
                        if not ok:
                            self.pad.tap("A")
                        self.tried[qo] = now
                        self.stats["interacts"] = self.stats.get("interacts", 0) + 1
                        act["do"] = "interact"
                    self._unstick(x, y, now, act)
                    return act
                if now > self.wander_until:
                    a = math.atan2(self.wander[1], self.wander[0]) + 1.2
                    self.wander, self.wander_until = (math.cos(a), math.sin(a)), now + 6
                dx, dy = self.wander
                act["do"] = "wander"
            if act["do"] == "seek":
                self.go(x, y, z, (x + dx, y + dy, z), dx, dy)
            else:
                self.pad.stick(*self.to_stick(dx, dy))
            self._unstick(x, y, now, act)
            return act

        d, dx, dy, n, o, h = foes[0][:6]
        act["target"] = f"{n} {round(d)}"
        act["thp"] = round(h, 1)
        if d <= MELEE:
            if not self.hit or self.hit[0] != o:
                self.hit = (o, now, h)
            elif now - self.hit[1] > 1.5:
                if h >= self.hit[2]:
                    self.ignore[o] = now + 20
                    self.seen.pop(o, None)
                    self.hit = None
                    act["do"] = "ignore"
                    return act
                self.hit = (o, now, h)
            self.pad.stick(*self.to_stick(dx, dy, 0.25))   # 살짝 그쪽을 보게
            self.pad.tap("X")
            self.stats["melee"] += 1
            self.stuck_since = None
            act["do"] = "melee"
            return act
        self.hit = None
        if self._chase_stuck(o, x, y, now, d):
            act["do"] = "unreachable"
            return act
        self.go(x, y, z, (x + dx, y + dy, z), dx, dy)
        act["do"] = "walk"
        self._unstick(x, y, now, act)
        return act

    def go(self, x, y, z, target, dx, dy):
        """이동: 클릭 이동이 되면 게임 길찾기(클릭), 안 되면 스틱으로 직진."""
        if self.clicker and now_ok(self):
            self.pad.stick(0, 0)
            if self.clicker.click_world(target, (x, y, z)):
                self.moved_by = "click"
                return
        self.pad.stick(*self.to_stick(dx, dy))
        self.moved_by = "stick"

    def _ahead(self, path, i, x, y, z, look=700.0):
        """경로를 따라 지금 점부터 look만큼 앞의 지점(클릭할 곳)."""
        px, py, pz = x, y, z
        left = look
        for j in range(i, len(path)):
            qx, qy, qz = path[j]
            seg = math.hypot(qx - px, qy - py)
            if seg >= left:
                t = left / seg if seg else 0
                return (px + (qx - px) * t, py + (qy - py) * t, pz + (qz - pz) * t)
            left -= seg
            px, py, pz = qx, qy, qz
        return path[-1]

    def _quest_target(self, x, y, z, now):
        """4000 안에서 90초 안에 안 건드려 본 가장 가까운 퀘스트 대상 (객체, 거리, 위치)."""
        best = None
        for o in list(self.r.quest_objs):
            if now - self.tried.get(o, -1e9) < 90:
                continue
            try:
                p = self.r.loc(o)
            except Exception:
                continue
            d = math.hypot(p[0] - x, p[1] - y)
            if d < 4000 and abs(p[2] - z) < 600 and (not best or d < best[1]):
                best = (o, d, p)
        return best

    def _chase_stuck(self, o, x, y, now, d=None):
        """몹을 쫓는데 4초 동안 그 몹과의 거리가 150도 안 줄면(벽 너머·높은 곳) 쫓던 몹들을 25초 무시.
        클릭 이동은 길을 돌아가느라 내가 움직이기는 해서, 내 위치가 아니라 '가까워졌는지'로 본다."""
        if d is None:
            d = 0.0
        if not self.chase or d < self.chase[2] - 150:
            self.chase = (set(), now, d)
        self.chase[0].add(o)
        if now - self.chase[1] > 4:
            for m in self.chase[0]:
                self.ignore[m] = now + 60
                self.seen.pop(m, None)
            self.chase = None
            return True
        return False

    @staticmethod
    def _key(p):
        return (round(p[0] / 50), round(p[1] / 50))

    def _unstick(self, x, y, now, act):
        """1.5초 넘게 제자리면 점프, 돌아다니는 중이면 방향도 바꿈."""
        if self.last_pos and math.hypot(x - self.last_pos[0], y - self.last_pos[1]) < 8:
            self.stuck_since = self.stuck_since or now
            if now - self.stuck_since > 1.5:
                self.pad.tap("A")
                self.stats["jumps"] += 1
                self.stuck_since = None
                self.wander_until = 0
                act["do"] = "jump"
        else:
            self.stuck_since = None
        self.last_pos = (x, y)


def main():
    app = find_ohs_app()
    if not app:
        log("Offline Hero Sync 폴더를 못 찾았어.")
        return
    sys.path.insert(0, app)
    import winproc  # noqa
    import uemem    # noqa
    import gamewin
    gamewin.prepare()
    try:
        pad = Pad()
    except Exception as e:
        log("가상 패드를 못 켰어:", e)
        return
    ue = uemem.UE(winproc.Process(), rescan=True)
    bot = Bot(ue, pad)
    try:
        import screen
        bot.clicker = screen.Clicker(ue, ue.p.pid)
        log("클릭 이동 켬(게임 길찾기 사용)")
    except Exception as e:
        log("클릭 이동 못 켬, 스틱으로 이동:", e)
    if not bot.r.player:
        log("내 캐릭터를 못 찾았어. 월드에 들어간 상태로 다시 해 줘.")
        return
    log("봇 준비 끝. 멈추려면 이 창에서 Ctrl+C.")
    gamewin.focus_game()
    time.sleep(0.5)
    t0 = time.time()
    last_hp, was_dead = None, False
    try:
        bot.calibrate()
        log(f"봇 시작({SECONDS:.0f}초)")
        with open(LOG, "w", encoding="utf-8") as f:
            while time.time() - t0 < SECONDS:
                tick = time.time()
                try:
                    a = bot.step()
                except Exception:
                    a = {"err": traceback.format_exc(limit=1).strip().splitlines()[-1]}
                    time.sleep(0.2)
                a["t"] = round(tick - t0, 2)
                f.write(json.dumps(a, ensure_ascii=False) + "\n")
                if "hp" in a:
                    if last_hp is not None and a["hp"] < last_hp:
                        bot.stats["dmg_taken"] += last_hp - a["hp"]
                    last_hp = a["hp"]
                dead = bool(a.get("dead"))
                if dead and not was_dead and last_hp is not None:   # 살아 있는 걸 본 뒤에 죽은 것만 셈
                    bot.stats["deaths"] += 1
                was_dead = dead
                print(f"\r{a.get('t'):6.1f}초 체력 {a.get('hp')} 영혼 {a.get('soul')} 적 {a.get('foes')} "
                      f"{a.get('do', a.get('err', ''))} {a.get('target', '')}            ", end="", flush=True)
                time.sleep(max(0, 1 / 15 - (time.time() - tick)))
    except KeyboardInterrupt:
        pass
    except Exception:
        log("\n오류:", traceback.format_exc())
    finally:
        bot.stop = True
        pad.reset()
    print()
    log(f"\n[결과] {time.time() - t0:.0f}초")
    for k, v in bot.stats.items():
        log(f"  {k}: {round(v, 1)}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
    print("이 폴더에 생긴 bot_result.txt와 bot_log.jsonl을 디스코드로 보내 줘.")
