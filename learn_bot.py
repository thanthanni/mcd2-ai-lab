"""마던2 스스로 배우는 봇 v1 (Q-러닝, 판을 거듭할수록 나아지는 걸 보는 용도).

길 찾기·몹 없을 때 움직임은 규칙 봇(rule_bot)을 그대로 쓰고,
몹이 있을 때 "무엇을 할지"만 스스로 고른다. 0.5초마다 상황을 보고 행동 하나를 골라 해 본 뒤
점수(몹에게 준 피해·처치는 +, 내가 받은 피해·죽음은 -)로 그 상황에서 그 행동의 값을 고친다.
배운 표는 q_table.json에 남아서 다음 실행 때 이어서 배운다. 처음엔 막 고르다가(탐험) 점점 배운 대로 한다.

상황(작게 나눔): 내 체력(낮음/중간/높음) × 근처 몹 수(1/2~3/4+) × 가장 가까운 몹 거리(근접/가까움/멂)
              × 영혼 충분 × 물약 있음  = 108가지
행동: 0 근접 공격  1 활 쏘기  2 물러나기  3 구르기  4 물약  5 유물
"""
from __future__ import annotations

import json
import math
import os
import random
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import rule_bot as rb                  # noqa: E402
from rule_bot import Bot, Pad, PASSIVE, SIGHT, ZGAP, MELEE  # noqa: E402
from state_probe import find_ohs_app  # noqa: E402

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 600.0
EPISODE = 120.0                        # 한 판 길이(학습 기록 단위)
QFILE = os.path.join(HERE, "q_table.json")
HIST = os.path.join(HERE, "learn_history.jsonl")
OUT = os.path.join(HERE, "learn_result.txt")
ACTIONS = ["melee", "shoot", "back", "roll", "potion", "artifact"]
ALPHA, GAMMA = 0.2, 0.8
DT = 0.5
lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


class Learner(Bot):
    def __init__(self, ue, pad):
        super().__init__(ue, pad)
        self.q = {}
        self.steps_total = 0
        if os.path.exists(QFILE):
            d = json.load(open(QFILE))
            self.q, self.steps_total = d["q"], d["steps"]
        self.prev = None              # (상황, 행동)
        self.mob_hp = {}              # 몹 → 지난번 체력
        self.last_art_any = 0.0

    def eps(self):
        return max(0.05, 0.5 * math.exp(-self.steps_total / 1500))

    def save(self):
        json.dump({"q": self.q, "steps": self.steps_total}, open(QFILE, "w"))

    def look(self):
        r, now = self.r, time.time()
        with self.lock:
            me, mobs = r.player, dict(r.mobs)
        x, y, z = r.loc(me)
        hp, hpmax = r.hp(me)
        if hp is None or not hpmax:
            return None
        soul = r.attr(me, "ATR_Soul", "Souls") or 0
        potions = r.attr(me, "ATR_Health", "HealthPotionCharges") or 0
        foes, hps = [], {}
        for o, n in mobs.items():
            if any(k in n for k in PASSIVE) or self.ignore.get(o, 0) > now:
                continue
            try:
                mx, my, mz = r.loc(o)
                h, m = r.hp(o)
            except Exception:
                continue
            if h is None:
                continue
            hps[o] = h
            d = math.hypot(mx - x, my - y)
            if h > 0 and d < SIGHT and abs(mz - z) < ZGAP:
                foes.append((d, mx - x, my - y, n, o, h, m))
        foes.sort(key=lambda f: f[0])
        return {"x": x, "y": y, "z": z, "hp": hp, "hpmax": hpmax, "soul": soul, "potions": potions, "foes": foes, "hps": hps}

    def state_key(self, s):
        f = s["foes"]
        hpb = 0 if s["hp"] / s["hpmax"] < 0.35 else 1 if s["hp"] / s["hpmax"] < 0.7 else 2
        near = len([x for x in f if x[0] < 700])
        nb = 0 if near <= 1 else 1 if near <= 3 else 2
        d = f[0][0] if f else 9999
        db = 0 if d <= MELEE + 40 else 1 if d < 700 else 2
        return f"{hpb}{nb}{db}{int(s['soul'] >= 40)}{int(s['potions'] >= 1)}"

    def dealt(self, s):
        """지난번보다 몹 체력이 줄어든 만큼(피해) + 사라졌거나 0이 된 몹(처치)."""
        dmg, kills = 0.0, 0
        for o, h in s["hps"].items():
            p = self.mob_hp.get(o)
            if p is not None and h < p:
                dmg += p - h
                if h <= 0:
                    kills += 1
        for o, p in self.mob_hp.items():
            if o not in s["hps"] and 0 < p < 15:
                kills += 1
        self.mob_hp = {o: h for o, h in s["hps"].items() if h > 0}
        return dmg, kills

    def do(self, a, s):
        f = s["foes"]
        if not f:
            return
        d, dx, dy = f[0][:3]
        close = [x for x in f if x[0] < 600] or f[:1]
        cx = sum(x[1] for x in close) / len(close)
        cy = sum(x[2] for x in close) / len(close)
        name = ACTIONS[a]
        if name == "melee":
            if d > MELEE:
                self.go(s["x"], s["y"], s.get("z", 0), (s["x"] + dx, s["y"] + dy, s.get("z", 0)), dx, dy)
                time.sleep(DT)
            else:
                self.pad.stick(*self.to_stick(dx, dy, 0.25))
                for _ in range(3):
                    self.pad.tap("X")
                    time.sleep(0.08)
        elif name == "shoot":
            self.pad.stick(*self.to_stick(dx, dy, 0.3))
            self.pad.trigger(left=False, hold=0.35)
        elif name == "back":
            self.pad.stick(*self.to_stick(-cx, -cy))
            time.sleep(DT)
        elif name == "roll":
            self.pad.stick(*self.to_stick(-cx, -cy))
            self.pad.tap("LEFT_SHOULDER")
            time.sleep(0.3)
        elif name == "potion":
            self.pad.trigger(left=True)
        elif name == "artifact":
            self.pad.stick(0, 0)
            b = "B" if self.last_art["B"] <= self.last_art["RIGHT_SHOULDER"] else "RIGHT_SHOULDER"
            self.pad.tap(b)
            self.last_art[b] = time.time()
        self.pad.stick(0, 0)

    def learn_step(self, ep):
        s = self.look()
        if s is None:
            time.sleep(0.2)
            return
        ep["fails"] = 0
        dmg, kills = self.dealt(s)
        dead = s["hp"] <= 0
        taken = max(0.0, ep.get("last_hp", s["hp"]) - s["hp"]) if not dead else 0
        ep["last_hp"] = s["hp"] if not dead else ep.get("last_hp", s["hpmax"])
        reward = 0.1 * dmg + 5 * kills - 0.3 * taken - (30 if dead and not ep.get("was_dead") else 0)
        ep["reward"] += reward
        ep["dealt"] += dmg
        ep["kills"] += kills
        ep["taken"] += taken
        if dead and not ep.get("was_dead"):
            ep["deaths"] += 1
        ep["was_dead"] = dead
        if dead:
            self.pad.reset()
            self.prev = None
            ep.setdefault("dead_since", time.time())
            if time.time() - ep["dead_since"] > 6:     # 쓰러진 화면이 오래가면 A로 넘기기 + 다시 훑기
                self.pad.tap("A")
                self.resync()
                ep["dead_since"] = time.time() - 4
            time.sleep(0.5)
            return
        ep.pop("dead_since", None)
        if not s["foes"]:
            # 몹 없을 땐 규칙 봇(안내선 따라가기)에게 맡기고 학습은 쉰다
            if self.prev:
                self._update(self.prev, reward, None)
                self.prev = None
            try:
                super().step()
            except Exception:
                pass
            time.sleep(1 / 15)
            return
        d0, o0 = s["foes"][0][0], s["foes"][0][4]
        if d0 > MELEE and self._chase_stuck(o0, s["x"], s["y"], time.time(), d0):
            ep["ignored"] = ep.get("ignored", 0) + 1     # 벽 너머·높은 곳 몹은 포기(학습에 안 넣음)
            self.prev = None
            return
        if d0 <= MELEE:
            self.chase = None
        k = self.state_key(s)
        qs = self.q.setdefault(k, [0.0] * len(ACTIONS))
        if self.prev:
            self._update(self.prev, reward, k)
        if random.random() < self.eps():
            a = random.randrange(len(ACTIONS))
        else:
            a = max(range(len(ACTIONS)), key=lambda i: qs[i])
        ep["choices"][ACTIONS[a]] = ep["choices"].get(ACTIONS[a], 0) + 1
        self.do(a, s)
        self.prev = (k, a)
        self.steps_total += 1

    def resync(self):
        """내 캐릭터가 바뀌었을 수 있으니(부활·로딩) 객체 표를 바로 다시 훑는다."""
        try:
            with self.lock:
                self.r.scan()
        except Exception:
            pass

    def _update(self, prev, reward, k2):
        k, a = prev
        qs = self.q.setdefault(k, [0.0] * len(ACTIONS))
        nxt = max(self.q.get(k2, [0.0] * len(ACTIONS))) if k2 else 0.0
        qs[a] += ALPHA * (reward + GAMMA * nxt - qs[a])


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
    pad = Pad()
    ue = uemem.UE(winproc.Process(), rescan=True)
    bot = Learner(ue, pad)
    try:
        import screen
        bot.clicker = screen.Clicker(ue, ue.p.pid)
        log("클릭 이동 켬(게임 길찾기 사용)")
    except Exception as e:
        log("클릭 이동 못 켬, 스틱으로 이동:", e)
    if not bot.r.player:
        log("내 캐릭터를 못 찾았어. 월드에 들어간 상태로 다시 해 줘.")
        return
    gamewin.focus_game()
    time.sleep(0.5)
    bot.calibrate()
    prior = sum(1 for _ in open(HIST)) if os.path.exists(HIST) else 0
    log(f"학습 봇 시작: {SECONDS:.0f}초, 한 판 {EPISODE:.0f}초. 지금까지 {prior}판, 학습 {bot.steps_total}걸음, 탐험률 {bot.eps():.2f}")
    t0 = time.time()
    try:
        while time.time() - t0 < SECONDS:
            ep = {"reward": 0.0, "dealt": 0.0, "kills": 0, "taken": 0.0, "deaths": 0, "choices": {}}
            te = time.time()
            while time.time() - te < EPISODE and time.time() - t0 < SECONDS:
                try:
                    bot.learn_step(ep)
                except Exception as e:
                    ep["fails"] = ep.get("fails", 0) + 1
                    msg = traceback.format_exc(limit=1).strip().splitlines()[-1]
                    ep.setdefault("errors", {})[msg] = ep.setdefault("errors", {}).get(msg, 0) + 1
                    if ep["fails"] % 15 == 0:                # 3초 넘게 계속 실패하면 다시 훑기 + A
                        bot.resync()
                        pad.tap("A")
                    time.sleep(0.2)
                print(f"\r판 {prior + 1}  {time.time() - te:5.0f}초  점수 {ep['reward']:7.1f}  처치 {ep['kills']}  "
                      f"받은 피해 {ep['taken']:.0f}  탐험률 {bot.eps():.2f}      ", end="", flush=True)
            prior += 1
            rec = {"ep": prior, "time": round(time.time()), "secs": round(time.time() - te),
                   "reward": round(ep["reward"], 1), "dealt": round(ep["dealt"]), "kills": ep["kills"],
                   "taken": round(ep["taken"]), "deaths": ep["deaths"], "eps": round(bot.eps(), 3),
                   "steps": bot.steps_total, "choices": ep["choices"], "errors": ep.get("errors", {})}
            with open(HIST, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            bot.save()
            print()
            log(f"판 {prior}: 점수 {rec['reward']} 처치 {rec['kills']} 준 피해 {rec['dealt']} 받은 피해 {rec['taken']} "
                f"사망 {rec['deaths']} 고른 행동 {rec['choices']}" + (f" 오류 {rec['errors']}" if rec["errors"] else ""))
    except KeyboardInterrupt:
        pass
    finally:
        bot.stop = True
        bot.save()
        pad.reset()
    log("\n[배운 것: 상황별 가장 좋다고 보는 행동]")
    names = {"0": "체력낮음", "1": "체력중간", "2": "체력높음"}
    for k, qs in sorted(bot.q.items()):
        best = max(range(len(ACTIONS)), key=lambda i: qs[i])
        if any(qs):
            log(f"  {names[k[0]]} 몹{['1', '2~3', '4+'][int(k[1])]} {['근접', '가까움', '멂'][int(k[2])]} "
                f"영혼{'O' if k[3] == '1' else 'X'} 물약{'O' if k[4] == '1' else 'X'} → {ACTIONS[best]} "
                f"({', '.join(f'{ACTIONS[i]} {qs[i]:.1f}' for i in range(len(ACTIONS)))})")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
