"""모방학습 봇: 장훈이 플레이 기록으로 배운 작은 신경망(bc_model.json)이 이동·버튼을 고른다.

- 적이 보이면(1300 안) 신경망이 조종: 이동 방향 9가지 중 하나 + 버튼(X·A·LB·B·RB·Y·L3·RT·LT)을 확률이 기준보다 높을 때 누름.
- 적이 없고 신경망이 2초 넘게 '멈춤'만 고르면 길찾기(안내선·퀘스트 대상)는 규칙 봇에 맡김.
진짜 패드는 빼고 실행. 결과는 bc_result.txt.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
import traceback

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from rule_bot import Bot, Pad, PASSIVE  # noqa: E402
from state_probe import find_ohs_app    # noqa: E402
import bc_state                          # noqa: E402

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 300.0
OUT = os.path.join(HERE, "bc_result.txt")
lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


class Net:
    def __init__(self, d):
        self.W = [np.array(w, dtype=np.float32) for w in d["W"]]
        self.b = [np.array(b, dtype=np.float32) for b in d["b"]]
        self.classes = d.get("classes")

    def __call__(self, x, softmax):
        h = x
        for i, (w, b) in enumerate(zip(self.W, self.b)):
            h = h @ w + b
            if i < len(self.W) - 1:
                h = np.maximum(h, 0)
        if softmax:
            e = np.exp(h - h.max())
            return e / e.sum()
        return 1 / (1 + np.exp(-h))


class BCBot(Bot):
    def __init__(self, ue, pad, model):
        super().__init__(ue, pad)
        self.m = model
        self.move = Net(model["move"])
        self.btn = Net(model["btn"])
        self.last_press = {}
        self.rt_on = False
        self.still_since = None
        self.counts = {}
        self.ev = {"dealt": 0.0, "taken": 0.0, "kills": 0, "deaths": 0}
        self.mob_hp = {}
        self.my_hp = None
        self.was_dead = False

    def score(self, row):
        """평가: 가까운 적(900)에게 준 피해·처치, 내가 받은 피해·죽음."""
        hp = row["me"]["hp"][0]
        if self.my_hp is not None and 0 < hp < self.my_hp:
            self.ev["taken"] += self.my_hp - hp
        dead = hp <= 0
        if dead and not self.was_dead:
            self.ev["deaths"] += 1
        self.was_dead = dead
        self.my_hp = hp
        cur = {}
        with self.lock:
            mobs = dict(self.r.mobs)
        for o, n in mobs.items():
            if any(p in n for p in PASSIVE):
                continue
            try:
                h, m = self.r.hp(o)
                mx, my, _ = self.r.loc(o)
            except Exception:
                continue
            if h is not None and math.hypot(mx - row["me"]["p"][0], my - row["me"]["p"][1]) < 900:
                cur[o] = (h, m)
        for o, (h, m) in cur.items():
            p = self.mob_hp.get(o)
            if p and h < p[0]:
                self.ev["dealt"] += p[0] - h
                if h <= 0:
                    self.ev["kills"] += 1
        for o, (p, m) in self.mob_hp.items():
            if o not in cur and m and p / m < 0.35:
                self.ev["kills"] += 1
        self.mob_hp = {o: hm for o, hm in cur.items() if hm[0] > 0}

    def row(self):
        """play_recorder.py와 같은 모양의 상태 한 줄."""
        r = self.r
        with self.lock:
            me_o, mobs, quest = r.player, dict(r.mobs), dict(r.quest_objs)
        x, y, z = r.loc(me_o)
        vel = r.vel(me_o)
        hp, hpmax = r.hp(me_o)
        row = {"me": {"p": [x, y, z], "v": list(vel), "hp": [hp or 0, hpmax or 0],
                      "soul": r.attr(me_o, "ATR_Soul", "Souls") or 0,
                      "pot": r.attr(me_o, "ATR_Health", "HealthPotionCharges"),
                      "roll": r.attr(me_o, "ATR_Movement", "RollCharges"),
                      "ammo": r.attr(me_o, "ATR_RangedAttack", "RangedAttackAmmoCount")}}
        foes = []
        for o, n in mobs.items():
            try:
                mx, my, mz = r.loc(o)
                d = math.hypot(mx - x, my - y)
                if d > 1500:
                    continue
                h, m = r.hp(o)
                if h is None or h <= 0:
                    continue
                try:
                    age = r.render_age(o)
                except Exception:
                    age = None
                foes.append([d, mx - x, my - y, mz - z, h, m or 0, n, age])
            except Exception:
                continue
        foes.sort(key=lambda f: f[0])
        row["foes"] = foes[:8]
        try:
            path, _ = r.guide_path((x, y))
            if path:
                dd = [math.hypot(p[0] - x, p[1] - y) for p in path]
                i = dd.index(min(dd))
                row["guide"] = [[p[0] - x, p[1] - y, p[2] - z] for p in path[i:i + 4]]
        except Exception:
            pass
        qs = []
        for o, n in quest.items():
            try:
                p = r.loc(o)
                d = math.hypot(p[0] - x, p[1] - y)
                if d < 2500:
                    qs.append([d, p[0] - x, p[1] - y, p[2] - z, n])
            except Exception:
                continue
        row["quest"] = sorted(qs, key=lambda q: q[0])[:3]
        return row, (x, y, z)

    def bc_step(self):
        now = time.time()
        row, (x, y, z) = self.row()
        self.score(row)
        if row["me"]["hp"][0] <= 0:
            self.pad.reset()
            return {"dead": True}
        f = np.array(bc_state.feats(row), dtype=np.float32)
        pm = self.move(f, softmax=True)
        k = int(self.move.classes[int(pm.argmax())])
        pb = self.btn(f, softmax=False)
        foes = [q for q in row["foes"] if not any(p in q[6] for p in PASSIVE) and q[0] < 1300
                and (q[7] is None or q[7] < 0.5 or q[0] < 350)]
        act = {"hp": round(row["me"]["hp"][0]), "foes": len(foes), "move": k}
        # 적도 없고 신경망이 계속 멈춤이면 길찾기는 규칙 봇에게
        if not foes and k == 0:
            self.still_since = self.still_since or now
            if now - self.still_since > 2:
                a = Bot.step(self)
                a["by"] = "rule"
                return a
        else:
            self.still_since = None
        if k == 0:
            self.pad.stick(0, 0)
        else:
            ang = (k - 1) * math.pi / 4
            self.pad.stick(*self.to_stick(math.cos(ang), math.sin(ang)))
        pressed = []
        for j, name in enumerate(self.m["outs"]):
            on = pb[j] > self.m["thr"][name]
            if name == "RT":
                if on != self.rt_on:
                    self.pad.p.right_trigger_float(1.0 if on else 0.0)
                    self.pad.p.update()
                    self.rt_on = on
                if on:
                    pressed.append("RT")
                continue
            if on and now - self.last_press.get(name, 0) > 0.3:
                if name == "LT":
                    self.pad.trigger(left=True)
                else:
                    self.pad.tap({"LB": "LEFT_SHOULDER", "RB": "RIGHT_SHOULDER", "L3": "LEFT_THUMB"}.get(name, name))
                self.last_press[name] = now
                pressed.append(name)
        for p in pressed:
            self.counts[p] = self.counts.get(p, 0) + 1
        act["by"] = "bc"
        act["press"] = pressed
        return act


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
    model = json.load(open(os.path.join(HERE, "bc_model.json")))
    bot = BCBot(ue, pad, model)
    try:
        import screen
        bot.clicker = screen.Clicker(ue, ue.p.pid)
    except Exception as e:
        log("클릭 이동 못 켬:", e)
    gamewin.focus_game()
    time.sleep(0.5)
    bot.calibrate()
    log(f"모방학습 봇 시작({SECONDS:.0f}초). 멈추려면 Ctrl+C.")
    t0 = time.time()
    by = {}
    try:
        while time.time() - t0 < SECONDS:
            tick = time.time()
            try:
                a = bot.bc_step()
            except Exception as e:
                a = {"err": str(e)[:60]}
                time.sleep(0.2)
            by[a.get("by", "err" if "err" in a else "dead")] = by.get(a.get("by", "err" if "err" in a else "dead"), 0) + 1
            print(f"\r{tick - t0:5.0f}초 체력 {a.get('hp')} 적 {a.get('foes')} 이동 {a.get('move')} {a.get('by', '')} "
                  f"{','.join(a.get('press', []))}          ", end="", flush=True)
            time.sleep(max(0, 0.1 - (time.time() - tick)))
    except KeyboardInterrupt:
        pass
    finally:
        bot.stop = True
        pad.reset()
    print()
    ev = {k: round(v) if isinstance(v, float) else v for k, v in bot.ev.items()}
    log(f"[결과] {time.time() - t0:.0f}초, 누가 조종했나 {by}, 신경망이 누른 버튼 {bot.counts}")
    log(f"[성적] 준 피해 {ev['dealt']}, 처치 {ev['kills']}, 받은 피해 {ev['taken']}, 사망 {ev['deaths']}")
    log(f"[규칙 봇 기록] {bot.stats}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
