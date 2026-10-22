"""걷기 담당(10-22 새로 뗌). "이 좌표까지 가"만 한다. 끼임 탈출·못 가는 길 판단·낭떠러지 점프는 전부 여기에만 둔다.

길 찾기: walkmap.json(서버에서 지금까지의 기록으로 만든 '걸어 본 길' 지도, 200칸) + walk_learned.json(이 PC에서 걸으며
새로 배운 칸·이음, 막혔던 이음)을 합친 그래프에서 A*. 지도에 없는 곳은 가장 가까운 아는 칸까지 지도로, 그다음은 직진.
움직이기: 다음 꺾이는 점 쪽으로 최대 900 앞을 클릭(게임 클릭 이동은 길찾기 없이 직선이라 모퉁이를 안 넘김), 클릭이 안 되면 스틱.
막힘(5초 동안 남은 거리가 150 안 줄어듦) 단계: 1 점프 → 2 옆으로 돌기(좌·우) → 3 8방향 점프·구르기 → 4 그 이음을 막힌 것으로
적고 다시 길 찾기. 다시 찾기를 3번 해도 안 되면 실패로 돌려준다.

사용:
    nav = Nav(reader, pad, clicker, to_stick, log)
    nav.goto((x, y, z), tol=250)      # 목표 정하기(같은 목표면 그대로 이어감)
    st = nav.step()                   # 0.1초마다: "moving" / "arrived" / "failed"
"""
from __future__ import annotations

import heapq
import json
import math
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
MAP = os.path.join(HERE, "walkmap.json")
LEARNED = os.path.join(HERE, "walk_learned.json")   # PC에만 있음(업데이트가 안 덮음)
JUMPS = os.path.join(HERE, "jump_spots.json")
DANGER = os.path.join(HERE, "danger_spots.json")
CELL, LAYER = 200, 400
LOOK = 900          # 경로를 따라 이만큼 앞을 클릭
PASS = 250          # 경로 점에 이만큼 가까우면 지나간 것으로 봄
STUCK_T = 5.0       # 이 시간 동안
STUCK_D = 150       # 남은 거리가 이만큼 안 줄면 막힘


def ckey(p):
    return f"{int(p[0] // CELL)},{int(p[1] // CELL)},{int(p[2] // LAYER)}"


def _off_line(a, b, p):
    """점 p가 선분 a-b에서 벗어난 거리(가로 평면)."""
    ax, ay, bx, by, px, py = a[0], a[1], b[0], b[1], p[0], p[1]
    L2 = (bx - ax) ** 2 + (by - ay) ** 2
    if not L2:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * (bx - ax) + (py - ay) * (by - ay)) / L2))
    return math.hypot(px - ax - t * (bx - ax), py - ay - t * (by - ay))


def ekey(a, b):
    return f"{a}|{b}" if a < b else f"{b}|{a}"


class Nav:
    def __init__(self, reader, pad, clicker, to_stick, log=print):
        self.r, self.pad, self.clicker, self.to_stick, self.log = reader, pad, clicker, to_stick, log
        self.cells, self.adj = {}, {}
        self.learned = {"cells": {}, "edges": [], "blocked": {}}
        self._load()
        self.goal = None
        self.path, self.i = [], 0
        self.best, self.best_t = 1e18, 0.0
        self.level, self.replans = 0, 0
        self.action_until, self.action = 0.0, None
        self.prev = None          # (시각, 위치) — 걸어서 이어진 칸 배우기
        self.last_save = time.time()
        self.stats = {"replans": 0, "jumps": 0, "detours": 0, "wedge": 0, "blocked": 0, "learned_cells": 0}
        try:
            self.jumps = json.load(open(JUMPS))
        except (OSError, ValueError):
            self.jumps = []
        try:
            self.danger = [tuple(p) for p in json.load(open(DANGER))]
        except (OSError, ValueError):
            self.danger = []

    # 지도 ------------------------------------------------------------------
    def _load(self):
        try:
            m = json.load(open(MAP))
            for k, c in m["cells"].items():
                self.cells[k] = tuple(c[:3])
            for a, b in m["edges"]:
                self._link(a, b)
        except (OSError, ValueError, KeyError) as e:
            self.log("[걷기] walkmap.json 못 읽음:", e)
        try:
            self.learned = json.load(open(LEARNED))
            for k, c in self.learned.get("cells", {}).items():
                self.cells.setdefault(k, tuple(c))
            for a, b in self.learned.get("edges", []):
                self._link(a, b)
        except (OSError, ValueError):
            pass
        self.learned.setdefault("blocked", {})
        self.log(f"[걷기] 지도 칸 {len(self.cells)}, 배운 칸 {len(self.learned.get('cells', {}))}, 막힌 이음 {len(self.learned['blocked'])}")

    def _link(self, a, b):
        self.adj.setdefault(a, set()).add(b)
        self.adj.setdefault(b, set()).add(a)

    def _learn(self, now, p):
        """걸으면서 지도 넓히기: 1.2초 안에 이어 지나간 두 칸을 잇는다(순간이동·낙하는 제외)."""
        k = ckey(p)
        if k not in self.cells:
            self.cells[k] = tuple(round(v) for v in p)
            self.learned.setdefault("cells", {})[k] = list(self.cells[k])
            self.stats["learned_cells"] += 1
        if self.prev:
            t0, p0 = self.prev
            k0 = ckey(p0)
            if k0 != k and now - t0 <= 1.2 and math.dist(p0[:2], p[:2]) <= 600 and abs(p[2] - p0[2]) <= 250:
                if k not in self.adj.get(k0, ()):
                    self._link(k0, k)
                    self.learned.setdefault("edges", []).append([k0, k])
                self.learned["blocked"].pop(ekey(k0, k), None)     # 실제로 지나갔으면 막힘 표시 지움
        self.prev = (now, p)
        if now - self.last_save > 60:
            self.save()

    def save(self):
        self.last_save = time.time()
        try:
            self.learned["edges"] = self.learned.get("edges", [])[-20000:]
            json.dump(self.learned, open(LEARNED, "w"), separators=(",", ":"))
        except OSError:
            pass

    def _nearest(self, p, maxd=1e18, linked=True):
        best, bd = None, maxd
        for k, c in self.cells.items():
            if linked and k not in self.adj:
                continue
            d = math.hypot(c[0] - p[0], c[1] - p[1]) + abs(c[2] - p[2]) * 0.7
            if d < bd:
                best, bd = k, d
        return best, bd

    def plan(self, me):
        """A*로 경로 점 목록을 만든다. 막힌 이음은 피하고, 위험 지역 칸은 아주 비싸게."""
        g = self.goal
        s, sd = self._nearest(me, 800)
        t, td = self._nearest(g)
        if not s or not t:
            return [g]
        now = time.time()
        blocked = {k for k, until in self.learned["blocked"].items() if until > now}

        def h(k):
            c = self.cells[k]
            return math.hypot(c[0] - self.cells[t][0], c[1] - self.cells[t][1])

        dist, prev = {s: 0.0}, {}
        pq = [(h(s), s)]
        done = set()
        while pq:
            _, u = heapq.heappop(pq)
            if u == t:
                break
            if u in done:
                continue
            done.add(u)
            cu = self.cells[u]
            for v in self.adj.get(u, ()):
                if ekey(u, v) in blocked:
                    continue
                cv = self.cells[v]
                w = math.hypot(cv[0] - cu[0], cv[1] - cu[1])
                if self.near_danger(cv[0], cv[1]):
                    w += 5000
                nd = dist[u] + w
                if nd < dist.get(v, 1e18):
                    dist[v], prev[v] = nd, u
                    heapq.heappush(pq, (nd + h(v), v))
        if t not in dist:
            return [g]
        keys = [t]
        while keys[-1] != s:
            keys.append(prev[keys[-1]])
        keys.reverse()
        pts = [self.cells[k] for k in keys]
        # 꺾이는 곳만 남김: 건너뛸 점들이 직선에서 60 넘게 벗어나면 그 앞에서 끊는다.
        # (게임 클릭 이동은 길찾기 없이 직선으로 감, 10-22 장훈 관찰 → 남긴 점 사이 직선이 실제로 걸었던 길이어야 함)
        out, a = [pts[0]], 0
        for b in range(2, len(pts)):
            if any(_off_line(pts[a], pts[b], pts[m]) > 60 for m in range(a + 1, b)):
                a = b - 1
                out.append(pts[a])
        out.append(pts[-1])
        if math.dist(pts[-1][:2], g[:2]) > 150:
            out.append(g)
        self.keys = keys
        return out

    def near_danger(self, px, py, rad=450):
        return any(math.hypot(px - a, py - b) < rad for a, b in self.danger)

    # 움직이기 --------------------------------------------------------------
    def goto(self, goal, tol=250):
        goal = tuple(goal)
        if self.goal and math.dist(goal[:2], self.goal[:2]) < 100:
            return
        self.goal, self.tol = goal, tol
        self.path, self.i, self.replans, self.level = [], 0, 0, 0
        self.best, self.best_t = 1e18, time.time()

    def remaining(self, me):
        if not self.path:
            return math.dist(me[:2], self.goal[:2])
        d = math.dist(me[:2], self.path[self.i][:2])
        for a, b in zip(self.path[self.i:], self.path[self.i + 1:]):
            d += math.dist(a[:2], b[:2])
        return d

    def _ahead(self, me):
        """클릭할 곳: 다음 꺾이는 점까지의 직선 위, 최대 LOOK 앞. 꺾이는 점을 넘어서 찍으면 게임이 직선으로 질러가다
        벽·낭떠러지에 걸리므로 모퉁이를 넘기지 않는다."""
        q = self.path[self.i]
        seg = math.dist(me[:2], q[:2])
        if seg <= LOOK:
            return q
        t = LOOK / seg
        return (me[0] + (q[0] - me[0]) * t, me[1] + (q[1] - me[1]) * t, me[2] + (q[2] - me[2]) * t)

    def step(self):
        now = time.time()
        me = self.r.loc(self.r.player)
        self._learn(now, me)
        if not self.goal:
            return "arrived"
        if math.dist(me[:2], self.goal[:2]) < self.tol and abs(me[2] - self.goal[2]) < 400:
            self.pad.stick(0, 0)
            return "arrived"
        if not self.path:
            self.path, self.i = self.plan(me), 0
            self.best, self.best_t = self.remaining(me), now
        # 지나간 점 넘기기(점에 닿았거나 다음 점이 더 가까워졌으면)
        while self.i < len(self.path) - 1:
            a, b = self.path[self.i], self.path[self.i + 1]
            if math.dist(me[:2], a[:2]) < PASS or math.dist(me[:2], b[:2]) < math.dist(a[:2], b[:2]) - 50:
                self.i += 1
            else:
                break
        rem = self.remaining(me)
        if rem < self.best - STUCK_D:
            self.best, self.best_t, self.level = rem, now, 0
        wp = self.path[self.i]
        dx, dy = wp[0] - me[0], wp[1] - me[1]
        if now < self.action_until:                   # 탈출 동작 중
            if self.action:
                self.pad.stick(*self.to_stick(*self.action))
            return "moving"
        if now - self.best_t > STUCK_T:
            r = self._unstuck(me, dx, dy, now)
            if r:
                return r
            return "moving"
        if self._jump_spot(me, dx, dy):               # 전에 떨어졌던 자리: 스틱으로 달리며 점프
            self.pad.stick(*self.to_stick(dx, dy))
            self.pad.tap("A")
            self.action, self.action_until = (dx, dy), now + 0.8
            return "moving"
        tgt = self._ahead(me)
        if self.clicker and self.clicker.click_world(tgt, me):
            self.pad.stick(0, 0)
        else:
            self.pad.stick(*self.to_stick(tgt[0] - me[0], tgt[1] - me[1]))
        return "moving"

    def _unstuck(self, me, dx, dy, now):
        self.level += 1
        self.best_t = now                            # 다음 단계까지 다시 5초
        if self.level == 1:
            # 제자리 = 메뉴·도움말 창이 열려 있을 수도 있음(10-22 18:1x 첫 판: '플레이 방법' 창을 보고 서 있음) → B로 닫고 점프
            self.pad.stick(0, 0)
            for _ in range(2):
                self.pad.tap("B")
                time.sleep(0.3)
            self.stats["jumps"] += 1
            self.action, self.action_until = (dx, dy), now + 1.0
            self.pad.stick(*self.to_stick(dx, dy))
            self.pad.tap("A")
        elif self.level in (2, 3):
            self.pad.tap("B")                        # 메뉴가 남아 있으면 닫기(A가 메뉴 안에서 '선택'이 되지 않게 먼저)
            time.sleep(0.3)
            self.stats["detours"] += 1
            side = 1 if self.level == 2 else -1
            self.action, self.action_until = (dx - dy * side * 1.5, dy + dx * side * 1.5), now + 1.5
            self.pad.tap("A")
        elif self.level == 4:
            self.stats["wedge"] += 1
            self.log("[걷기] 막힘 → 8방향 점프·구르기")
            self.pad.tap("B")
            time.sleep(0.3)
            x0, y0 = me[:2]
            for k in range(16):
                a = (k % 8) * math.pi / 4 + (0.4 if k >= 8 else 0)
                self.pad.stick(*self.to_stick(math.cos(a), math.sin(a)))
                time.sleep(0.15)
                self.pad.tap("A" if k % 2 == 0 else "LEFT_SHOULDER")
                time.sleep(0.6)
                p = self.r.loc(self.r.player)
                if math.dist(p[:2], (x0, y0)) > 150:
                    break
            self.pad.stick(0, 0)
        else:
            # 이 구간은 못 지나감 → 막힌 이음으로 적고(30분) 다시 길 찾기
            k0 = ckey(me)
            nxt = getattr(self, "keys", None)
            target = ckey(self.path[self.i]) if self.path else None
            for k1 in ([target] if target else []) + [k for k in (nxt or []) if k in self.adj.get(k0, ())][:2]:
                self.learned["blocked"][ekey(k0, k1)] = now + 1800
                self.stats["blocked"] += 1
            self.replans += 1
            self.stats["replans"] += 1
            self.level = 0
            self.path = []
            self.log(f"[걷기] 길 다시 찾기 {self.replans}번째 (남은 {self.remaining(me):.0f})")
            if self.replans > 3:
                self.save()
                return "failed"
        return None

    def _jump_spot(self, me, dx, dy):
        n = math.hypot(dx, dy) or 1
        if self.near_danger(me[0] + dx / n * 300, me[1] + dy / n * 300):
            return False
        for sx, sy, hx, hy in self.jumps:
            if math.hypot(me[0] - sx, me[1] - sy) < 150 and (dx * hx + dy * hy) / n > 0.5:
                return True
        return False
