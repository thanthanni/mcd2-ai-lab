"""스스로 배우는 봇 v2 (PPO 강화학습, 규칙 없음). 판단은 전부 신경망이 한다.

보는 것: 상태 숫자 69개(bc_state.feats와 같음: 내 정보·가까운 적 5·안내선 3점·퀘스트 대상 2).
하는 것: 0.1초마다 63가지 중 하나 = 이동 9가지(멈춤+8방향, 스틱) × 버튼 7가지(없음·X·A·LB·RT·유물·LT).
점수: 몹에게 준 피해·처치 +, 받은 피해·죽음 -, 안내선/퀘스트 대상에 가까워지면 +, 처음 가 보는 곳 +, 시간마다 조금 -.
처음 한 번은 장훈이 플레이 기록(play_*.jsonl)을 흉내 내서 시작하고, 그다음부터는 점수만 보고 스스로 고친다.
배운 것은 ppo_policy.pt에 계속 쌓인다. 결과는 ppo_log.jsonl(1,024걸음마다 한 줄)·ppo_result.txt.
규칙은 안전장치만 남김: 게임 창 앞으로, 죽으면 기다렸다가 A, 진짜 패드 빼기 기다림.
"""
from __future__ import annotations

import glob
import json
import math
import os
import sys
import time
import traceback

import numpy as np
import torch
import torch.nn as nn

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from rule_bot import Bot, Pad, PASSIVE, SIGHT   # noqa: E402  (패드·스틱 방향·상태 훑기만 씀, 규칙 판단은 안 씀)
from bc_bot import BCBot                 # noqa: E402  (상태 한 줄 만들기·성적 세기만 빌림)
from state_probe import find_ohs_app     # noqa: E402
import bc_state                           # noqa: E402
import kfeat                              # noqa: E402  (게임 지식: 몹 성질)

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 else 1800.0
FIELD = os.path.join(HERE, "field_pos.json")
SNAPS = os.path.join(HERE, "snaps")
POLICY = os.path.join(HERE, "ppo_policy.pt")
LOG = os.path.join(HERE, "ppo_log.jsonl")
OUT = os.path.join(HERE, "ppo_result.txt")
BUTTONS = ["none", "X", "A", "LB", "RT", "ART", "LT"]
NA = 9 * len(BUTTONS)
NOBS = kfeat.NOBS                     # 상태 69 + 몹 지식 30
DT = 0.1
ROLL = 1024
lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


class AC(nn.Module):
    def __init__(self):
        super().__init__()
        self.body = nn.Sequential(nn.Linear(NOBS, 256), nn.Tanh(), nn.Linear(256, 256), nn.Tanh())
        self.pi = nn.Linear(256, NA)
        self.v = nn.Linear(256, 1)

    def forward(self, x):
        h = self.body(x)
        return self.pi(h), self.v(h).squeeze(-1)


DEMO = None   # (관찰, 행동) 텐서: 장훈이 플레이 기록


def load_demos(dev):
    """play_*.jsonl → (X, Y) 텐서. 강화학습 중에도 '장훈이처럼 하기' 손실로 계속 섞어 쓴다."""
    global DEMO
    paths = sorted(glob.glob(os.path.join(glob.escape(HERE), "play_*.jsonl")))
    if not paths:
        return None
    X, M, B = bc_state.load(paths, featfn=kfeat.feats)
    outs = bc_state.OUTS                  # X A LB B RB Y L3 RT LT
    idx = {n: i for i, n in enumerate(outs)}
    acts = []
    for m, b in zip(M, B):
        if b[idx["LT"]]:
            k = 6
        elif b[idx["LB"]]:
            k = 3
        elif b[idx["A"]]:
            k = 2
        elif b[idx["B"]] or b[idx["RB"]] or b[idx["Y"]]:
            k = 5
        elif b[idx["X"]]:
            k = 1
        elif b[idx["RT"]]:
            k = 4
        else:
            k = 0
        acts.append(int(m) * len(BUTTONS) + k)
    DEMO = (torch.tensor(X, device=dev), torch.tensor(acts, device=dev))
    return DEMO


def bc_pretrain(net, dev):
    """장훈이 플레이 기록으로 처음 흉내. 기록이 없으면 건너뜀."""
    d = DEMO or load_demos(dev)
    if not d:
        return 0
    X, Y = d
    opt = torch.optim.Adam(net.parameters(), lr=1e-3)
    for it in range(600):
        i = torch.randint(0, len(X), (256,), device=dev)
        logits, _ = net(X[i])
        loss = nn.functional.cross_entropy(logits, Y[i])
        opt.zero_grad()
        loss.backward()
        opt.step()
    with torch.no_grad():
        acc = (net(X)[0].argmax(-1) == Y).float().mean().item()
    log(f"처음 흉내: 장훈 기록 {len(X)}장면, 맞힘 {acc:.2f}")
    return len(X)


class Agent(Bot):
    row = BCBot.row
    score = BCBot.score

    def __init__(self, ue, pad):
        super().__init__(ue, pad)
        self.ev = {"dealt": 0.0, "taken": 0.0, "kills": 0, "deaths": 0}
        self.mob_hp, self.my_hp, self.was_dead = {}, None, False
        self.visited = set()
        self.prev_goal = None
        self.rt_on = False
        self.last_tap = 0.0
        self.dead_since = None
        self.mask = np.ones(NA, dtype=bool)
        self.pos, self.anchor, self.unstuck, self.in_town = None, None, 0, False
        self.last_hostile = time.time()
        self.town_t, self.field_saved = None, 0.0
        try:
            self.field_pos = tuple(json.load(open(FIELD, encoding="utf-8")))
        except (OSError, ValueError):
            self.field_pos = (22000.0, 14000.0, 4400.0)   # 기록에서 몹이 많던 필드(마을 북쪽)

    def snap(self, tag):
        """게임 창 안쪽만 작은 JPG로 저장(게임 창이 맨 앞일 때만, 다른 화면은 절대 안 찍음). 판이 끝나면 묶어서 보냄."""
        now = time.time()
        if now - getattr(self, "last_snap", 0) < 20 or not self.clicker:
            return
        try:
            import ctypes
            import screen
            from PIL import ImageGrab
            if ctypes.windll.user32.GetForegroundWindow() != self.clicker.hwnd:
                return
            x, y, w, h = screen.client_rect(self.clicker.hwnd)
            img = ImageGrab.grab(bbox=(x, y, x + w, y + h))
            img.thumbnail((960, 540))
            os.makedirs(SNAPS, exist_ok=True)
            img.save(os.path.join(SNAPS, time.strftime("%H%M%S") + f"_{tag}.jpg"), quality=60)
            self.last_snap = now
        except Exception:
            pass

    def exploring(self):
        """싸울 몹이 4초 넘게 안 보이면 True(그동안은 길찾기 두뇌가 움직임)."""
        return time.time() - self.last_hostile > 4

    def revive(self, t0, seconds):
        """죽으면: 멈추고 6초 뒤부터 A(부활). 되살아나면 마을이라 check_stuck이 필드 쪽으로 걸어 나간다."""
        self.pad.reset()
        self.rt_on = False
        self.snap("dead")
        t_dead = time.time()
        while time.time() - t0 < seconds:
            time.sleep(1)
            try:
                _, _, dead, _ = self.observe()
            except Exception:
                continue
            if not dead:
                break
            if time.time() - t_dead > 6:
                self.pad.tap("A")
        time.sleep(3)
        for _ in range(2):                    # 부활 창 등 닫기. 마을이면 check_stuck이 필드 쪽으로 걸어 나감
            self.pad.tap("B")
            time.sleep(0.4)
        self.visited = set()
        self.prev_goal = None

    def check_stuck(self):
        """40초 넘게 150 안쪽에서 못 벗어나면 갇힌 것(메뉴가 열렸거나, 창이 뒤로 갔거나, 마을에 갇힘).
        1번째: 게임 창을 앞으로 + B(메뉴 닫기). 2번째부터: 길찾기 두뇌로 안 가 본 쪽 탐험(마을이면 위에서 Z)."""
        if self.pos is None:
            return
        now = time.time()
        if now - getattr(self, "last_tick_snap", 0) > 180:     # 3분마다 한 장(평소 모습)
            self.last_tick_snap = now
            self.snap("tick")
        # 마을(허수아비·마을 주민이 보임): 마지막으로 싸웠던 필드 쪽으로 걸어 나간다.
        # (Z는 순간이동이 아니라 지도를 여는 키라서 안 씀, 10-21 확인) 15초마다 B로 열린 창(지도·상점)을 닫음.
        if self.in_town:
            if getattr(self, "town_t", None) is None:
                self.town_t, self.town_b = now, now
                log(f"[마을] 필드 {tuple(round(v) for v in self.field_pos[:2])} 쪽으로 걸어 나감")
                self.snap("town")
            if now - self.town_b > 15:
                self.pad.reset()
                self.pad.tap("B")
                self.town_b = now
            x, y, z = self.pos3
            gx, gy = self.field_pos[0] - x, self.field_pos[1] - y
            k = min(1.0, 1000 / max(math.hypot(gx, gy), 1))
            self.go(x, y, z, (x + gx * k, y + gy * k, z), gx, gy)
            self._unstick(x, y, now, {})
            if now - self.town_t > 120 and now - getattr(self, "town_log", 0) > 120:
                self.town_log = now
                self.unstuck += 1
                log("[마을] 2분째 못 나감")
                self.snap("town_stuck")
            self.anchor = None
            return
        if self.town_t is not None:
            log(f"[마을] 빠져나옴({now - self.town_t:.0f}초)")
        self.town_t = None
        if self.anchor is None or math.hypot(self.pos[0] - self.anchor[0], self.pos[1] - self.anchor[1]) > 150:
            self.anchor, self.anchor_t, self.tries = self.pos, now, 0
            return
        if now - getattr(self, "last_fight", 0) < 10:     # 제자리에서 싸우는 중이면 갇힌 게 아님
            self.anchor_t = max(self.anchor_t, now - 30)
        if now - self.anchor_t < 40:
            return
        self.pad.reset()
        self.rt_on = False
        self.unstuck += 1
        if self.tries == 0:
            log("[갇힘] 40초째 제자리 → 창 앞으로 + B")
            self.snap("stuck")
            try:
                import gamewin
                gamewin.focus_game()
            except Exception:
                pass
            time.sleep(0.5)
            for _ in range(2):
                self.pad.tap("B")
                time.sleep(0.5)
        else:                                          # 필드에서 Z를 누르면 부활 제단으로 되돌아가 버림 → 탐험으로 빠져나감
            log("[갇힘] 또 제자리 → 길찾기 두뇌로 안 가 본 쪽 탐험")
            self.snap("stuck2")
            self.last_hostile = 0
            self.wander_until = 0
            self.cur_path = None
        self.tries += 1
        self.anchor_t = time.time()

    def back_to_field(self):
        """죽으면 브레이브 헤이븐(마을)에서 되살아난다. 텔레포트 동상 단축키 Z를 눌러 마지막 부활 제단(필드)으로 돌아간다
        (knowledge/mechanics.md 9장). 확인 창이 뜰 수 있어서 A도 한 번 누르고, 불러오기를 기다린다."""
        import ctypes
        u32 = ctypes.windll.user32
        try:
            import gamewin
            gamewin.focus_game()
        except Exception:
            pass
        time.sleep(3)
        for _ in range(2):                                                 # 열려 있는 창(장비 강화 등)부터 닫기
            self.pad.tap("B")
            time.sleep(0.4)
        u32.keybd_event(0x5A, u32.MapVirtualKeyW(0x5A, 0), 0, 0)          # Z 누름
        time.sleep(0.1)
        u32.keybd_event(0x5A, u32.MapVirtualKeyW(0x5A, 0), 2, 0)          # Z 뗌
        time.sleep(1.5)
        self.pad.tap("A")                                                  # 확인 창이 뜨면 확인
        time.sleep(8)                                                      # 불러오기
        try:
            row, _ = self.row()
            if any("Town" in f[6] or "TargetDummy" in f[6] for f in row["foes"]):
                for _ in range(2):                                         # 아직 마을이면: A로 잘못 연 창이 있을 수 있어서 닫기
                    self.pad.tap("B")
                    time.sleep(0.4)
        except Exception:
            pass
        self.visited = set()

    def goal_dist(self, row):
        g = row.get("guide") or []
        if len(g) > 1:
            return math.hypot(g[1][0], g[1][1])
        q = row.get("quest") or []
        if q:
            return q[0][0]
        return None

    def act(self, a):
        mv, bt = divmod(a, len(BUTTONS))
        if mv == 0:
            self.pad.stick(0, 0)
        else:
            ang = (mv - 1) * math.pi / 4
            self.pad.stick(*self.to_stick(math.cos(ang), math.sin(ang)))
        name = BUTTONS[bt]
        want_rt = name == "RT"
        if want_rt != self.rt_on:
            self.pad.p.right_trigger_float(1.0 if want_rt else 0.0)
            self.pad.p.update()
            self.rt_on = want_rt
        now = time.time()
        if name in ("X", "A", "LB", "ART", "LT") and now - self.last_tap > 0.15:
            if name == "LT":
                self.pad.trigger(left=True, hold=0.05)
            elif name == "ART":
                self.pad.tap("B" if int(now) % 2 else "RIGHT_SHOULDER", hold=0.05)
            else:
                self.pad.tap({"LB": "LEFT_SHOULDER"}.get(name, name), hold=0.05)
            self.last_tap = now

    def observe(self):
        """(관찰, 보상, 죽음 여부, 기록용 값). 보상은 지난 걸음 이후 바뀐 것으로 계산."""
        row, (x, y, z) = self.row()
        before = dict(self.ev)
        self.score(row)
        d = {k: self.ev[k] - before[k] for k in self.ev}
        dead = row["me"]["hp"][0] <= 0
        self.pos, self.pos3 = (x, y), (x, y, z)
        if any(f[0] < SIGHT and not any(k in f[6] for k in PASSIVE) and (f[0] < 350 or (f[7] is not None and f[7] < 0.5))
               for f in row["foes"]):
            self.last_hostile = time.time()
            if not any("Town" in f[6] or "TargetDummy" in f[6] for f in row["foes"]) and time.time() - self.field_saved > 60:
                self.field_pos, self.field_saved = (x, y, z), time.time()     # 싸운 곳 = 돌아갈 필드
                try:
                    with open(FIELD, "w", encoding="utf-8") as f:
                        json.dump(self.field_pos, f)
                except OSError:
                    pass
        self.in_town = any("Town" in f[6] or "TargetDummy" in f[6] for f in row["foes"])
        if d["dealt"] > 0 or d["taken"] > 0:
            self.last_fight = time.time()
        r = 0.1 * d["dealt"] + 3 * d["kills"] - 0.2 * d["taken"] - 20 * d["deaths"] - 0.01
        gd = self.goal_dist(row)
        if gd is not None and self.prev_goal is not None:
            r += float(np.clip((self.prev_goal - gd) * 0.002, -0.5, 0.5))
        self.prev_goal = gd
        cell = (int(x // 500), int(y // 500))
        if cell not in self.visited:
            self.visited.add(cell)
            r += 0.3
        # 게임 지식 보상: 자폭하는 몹(크리퍼 등)에 250 안으로 붙어 있으면 조금씩 감점
        for f in row["foes"]:
            k = kfeat.info(f[6])
            if k and k["explode"] and f[0] < 250:
                r -= 0.05
        obs = np.array(kfeat.feats(row), dtype=np.float32)
        self.mask = self.knowledge_mask(row)
        return obs, r, dead, d

    def knowledge_mask(self, row):
        """게임 지식으로 '지금 의미 없는 버튼'을 막는다(무엇을 할지는 신경망이 정함).
        물약: 남아 있고 체력 85% 아래일 때만 / 유물: 영혼 40 넘고 보이는 적이 900 안에 있을 때만 /
        구르기: 구르기 횟수 남았을 때만 / 활: 화살 있고 1300 안에 보이는 적이 있을 때만 / 근접: 600 안에 적이 있을 때만."""
        me = row["me"]
        hp, hpm = me["hp"]
        foes = [f for f in row["foes"] if not any(p in f[6] for p in PASSIVE) and (f[7] is None or f[7] < 0.5 or f[0] < 350)]
        ok = {"none": True, "X": any(f[0] < 600 for f in foes), "A": True,
              "LB": (me.get("roll") or 0) >= 1,
              "RT": (me.get("ammo") or 0) >= 1 and any(f[0] < 1300 for f in foes),   # 활: 보이는 적이 있을 때만
              "ART": (me.get("soul") or 0) >= 40 and any(f[0] < 900 for f in foes),
              "LT": (me.get("pot") or 0) >= 1 and hpm > 0 and hp / hpm < 0.85}
        m = np.zeros(NA, dtype=bool)
        for k, name in enumerate(BUTTONS):
            if ok[name]:
                m[k::len(BUTTONS)] = True
        return m


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
    agent = Agent(ue, pad)
    try:
        import screen
        agent.clicker = screen.Clicker(ue, ue.p.pid)    # 길찾기 두뇌는 클릭 이동(게임 길찾기)을 씀
    except Exception as e:
        log("클릭 이동 못 켬:", e)
    gamewin.focus_game()
    time.sleep(0.5)
    agent.calibrate()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    net = AC().to(dev)
    opt = torch.optim.Adam(net.parameters(), lr=3e-4)
    total = 0
    if os.path.exists(POLICY) and torch.load(POLICY, map_location="cpu").get("nobs") != NOBS:
        os.replace(POLICY, POLICY + ".old")           # 입력 모양이 바뀐 옛 정책은 치워 두고 새로 시작
        log("입력이 바뀌어서 정책을 새로 시작해(옛 것은 ppo_policy.pt.old)")
    if os.path.exists(POLICY):
        ck = torch.load(POLICY, map_location=dev)
        net.load_state_dict(ck["net"])
        opt.load_state_dict(ck["opt"])
        total = ck.get("steps", 0)
        log(f"이어서 학습: 지금까지 {total}걸음")
    else:
        bc_pretrain(net, dev)
    if DEMO is None:
        load_demos(dev)
    if DEMO is not None:
        log(f"모방 손실도 같이 씀: 기록 {len(DEMO[0])}장면")
    log(f"강화학습 시작({SECONDS:.0f}초, {dev}). 멈추려면 Ctrl+C.")
    try:
        train_loop(agent, net, opt, dev, SECONDS, total)
    except KeyboardInterrupt:
        pass
    finally:
        agent.stop = True
        pad.reset()
        try:                                  # 찍은 화면을 한 파일로 묶음(자동 실행기가 서버로 보냄)
            import zipfile
            shots = sorted(glob.glob(os.path.join(SNAPS, "*.jpg")))
            if shots:
                with zipfile.ZipFile(os.path.join(HERE, time.strftime("snaps_%m%d_%H%M.zip")), "w") as z:
                    for f in shots:
                        z.write(f, os.path.basename(f))
                for f in shots:
                    os.remove(f)
        except Exception as e:
            log("화면 묶기 실패:", e)


def train_loop(agent, net, opt, dev, seconds, total):
    SECONDS = seconds
    t0 = time.time()
    obs, _, _, _ = agent.observe()
    if True:
        while time.time() - t0 < SECONDS:
            O, A, LP, V, R, D, MK = [], [], [], [], [], [], []
            ep = {"reward": 0.0, "dealt": 0.0, "kills": 0, "taken": 0.0, "deaths": 0, "acts": [0] * NA, "explore": 0}
            exploring = False
            while len(O) < ROLL and time.time() - t0 < SECONDS:
                tick = time.time()
                if agent.in_town:                     # 마을: 아무것도 안 누름(NPC를 눌러 마법부여 창 등을 여는 것 방지), 동상(Z)으로 나가기만
                    agent.pad.reset()
                    agent.rt_on = False
                    if D:
                        D[-1] = True
                    agent.check_stuck()
                    time.sleep(DT)
                    try:
                        obs, _, _, _ = agent.observe()
                    except Exception:
                        time.sleep(0.3)
                    continue
                if agent.exploring():                 # 싸울 몹이 없으면: 길찾기 두뇌(안내선·퀘스트·먼 몹 찾아가기)가 이동
                    if not exploring:
                        agent.pad.reset()
                        agent.rt_on = False
                        if D:
                            D[-1] = True              # 학습 구간은 여기서 끊김
                        exploring = True
                    try:
                        agent.step()
                    except Exception:
                        pass
                    time.sleep(max(0, DT - (time.time() - tick)))
                    try:
                        obs, _, dead, d = agent.observe()
                    except Exception:
                        time.sleep(0.3)
                        continue
                    ep["explore"] += 1
                    for k in ("dealt", "kills", "taken", "deaths"):
                        ep[k] += d[k]
                    if dead:
                        agent.revive(t0, SECONDS)
                    else:
                        agent.check_stuck()
                    continue
                if exploring:
                    agent.pad.reset()                 # 길찾기 두뇌가 누르던 것 놓고 신경망에게 넘김
                    exploring = False
                with torch.no_grad():
                    mask = agent.mask.copy()
                    logits, v = net(torch.tensor(obs, device=dev)[None])
                    logits = logits.masked_fill(~torch.tensor(mask, device=dev)[None], -1e9)
                    dist = torch.distributions.Categorical(logits=logits)
                    a = dist.sample()
                a_i = int(a.item())
                agent.act(a_i)
                time.sleep(max(0, DT - (time.time() - tick)))
                try:
                    nobs, r, dead, d = agent.observe()
                except Exception:
                    time.sleep(0.3)
                    continue
                O.append(obs)
                MK.append(mask)
                A.append(a_i)
                LP.append(float(dist.log_prob(a).item()))
                V.append(float(v.item()))
                R.append(r)
                D.append(dead)
                ep["reward"] += r
                ep["acts"][a_i] += 1
                for k in ("dealt", "kills", "taken", "deaths"):
                    ep[k] += d[k]
                obs = nobs
                if not dead:
                    agent.check_stuck()
                if dead:                              # 안전장치: 죽으면 멈추고 기다렸다가 A, 되살아나면 필드로
                    agent.revive(t0, SECONDS)
            if len(O) < 64:
                break
            # PPO 갱신(GAE)
            with torch.no_grad():
                _, last_v = net(torch.tensor(obs, device=dev)[None])
            gamma, lam = 0.99, 0.95
            adv = np.zeros(len(R), dtype=np.float32)
            gae = 0.0
            for i in reversed(range(len(R))):
                nv = float(last_v.item()) if i == len(R) - 1 else V[i + 1]
                nonterm = 0.0 if D[i] else 1.0
                delta = R[i] + gamma * nv * nonterm - V[i]
                gae = delta + gamma * lam * nonterm * gae
                adv[i] = gae
            ret = adv + np.array(V, dtype=np.float32)
            To = torch.tensor(np.array(O), device=dev)
            Ta = torch.tensor(A, device=dev)
            Tm = torch.tensor(np.array(MK), device=dev)
            Tlp = torch.tensor(LP, device=dev)
            Tadv = torch.tensor((adv - adv.mean()) / (adv.std() + 1e-8), device=dev)
            Tret = torch.tensor(ret, device=dev)
            agent.pad.stick(0, 0)
            for _ in range(4):
                perm = torch.randperm(len(O), device=dev)
                for s in range(0, len(O), 256):
                    i = perm[s:s + 256]
                    logits, v = net(To[i])
                    logits = logits.masked_fill(~Tm[i], -1e9)
                    dist = torch.distributions.Categorical(logits=logits)
                    ratio = torch.exp(dist.log_prob(Ta[i]) - Tlp[i])
                    pl = -torch.min(ratio * Tadv[i], torch.clamp(ratio, 0.8, 1.2) * Tadv[i]).mean()
                    vl = ((v - Tret[i]) ** 2).mean()
                    ent = dist.entropy().mean()
                    loss = pl + 0.5 * vl - 0.01 * ent
                    if DEMO is not None:                  # 장훈이처럼 하기(모방) 손실을 계속 섞음
                        w = max(0.1, 1.0 - total / 200_000)
                        j = torch.randint(0, len(DEMO[0]), (128,), device=dev)
                        loss = loss + w * nn.functional.cross_entropy(net(DEMO[0][j])[0], DEMO[1][j])
                    opt.zero_grad()
                    loss.backward()
                    nn.utils.clip_grad_norm_(net.parameters(), 0.5)
                    opt.step()
            total += len(O)
            torch.save({"net": net.state_dict(), "opt": opt.state_dict(), "steps": total, "nobs": NOBS}, POLICY)
            mv = [sum(ep["acts"][m * len(BUTTONS):(m + 1) * len(BUTTONS)]) for m in range(9)]
            bt = [sum(ep["acts"][k::len(BUTTONS)]) for k in range(len(BUTTONS))]
            rec = {"time": round(time.time()), "steps": total, "n": len(O), "reward": round(ep["reward"], 1),
                   "dealt": round(ep["dealt"]), "kills": ep["kills"], "taken": round(ep["taken"]), "deaths": ep["deaths"],
                   "cells": len(agent.visited), "unstuck": agent.unstuck, "explore": ep["explore"], "entropy": round(float(ent.item()), 2),
                   "move": mv, "buttons": dict(zip(BUTTONS, bt))}
            with open(LOG, "a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            log(f"[{total}걸음] 점수 {rec['reward']} 처치 {rec['kills']} 준 피해 {rec['dealt']} 받은 피해 {rec['taken']} "
                f"사망 {rec['deaths']} 새 칸 {rec['cells']} 탈출 {rec['unstuck']} 길찾기 {rec['explore']} 버튼 {rec['buttons']}")
    return total


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
