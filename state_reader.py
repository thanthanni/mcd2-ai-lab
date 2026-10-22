"""마던2 실시간 상태 읽기(읽기만 함).

state_probe로 찾은 길:
  내 캐릭터 = PlayerCharacter 계열, 몹 = MobCharacter 계열(QuestCharacter는 NPC)
  위치 = RootComponent.RelativeLocation(double 3개), 속도 = CharacterMovement.Velocity
  체력 = 주인이 그 캐릭터인 ATR_Health의 Health / HealthMax (FGameplayAttributeData 현재값 @+0xC)
처음 한 번 내 캐릭터의 ATR_* 묶음(영혼·유물 쿨타임 후보)을 전부 적고,
30초 동안 초당 10번 읽어서 체력·영혼 변화와 몹 수를 state_reader.txt에 남긴다.
그동안 몹과 싸우고, 물약 한 번, 유물 한 번 써 줘.
"""
from __future__ import annotations

import json
import os
import struct
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "state_reader.txt")
LOG = os.path.join(HERE, "state_log.jsonl")
SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].replace(".", "", 1).isdigit() else 30.0
HZ = 10
lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


from state_probe import find_ohs_app  # noqa: E402


VALID_CLS: set = set()   # 훑을 때 실제로 본 클래스 주소(모든 Reader가 같이 씀)
LOOT = ("Pickup", "Loot", "Chest", "Emerald", "Drop")     # 줍는 것·상자 클래스 이름 조각
LOOT_SKIP = ("W_", "GA_", "GE_", "GCN_", "AS_", "BTTask", "BP_Loot_Table", "DT_")


class Reader:
    def __init__(self, ue):
        self.ue = ue
        self.chain = {}      # class addr -> [이름, 상위 이름...]
        self.off = {}        # (class addr, 필드) -> offset
        self.player = None
        self.mobs = {}       # actor -> 클래스 이름
        self.npcs = set()
        self.atr = {}        # actor -> {ATR 클래스 이름: 객체}
        self.navpaths = []   # NavigationPath(길 안내선 경로 후보)
        self.trail = None    # BP_PlayerGuidanceTrail_Visual_C
        self.loot = {}       # 줍는 것·상자(클래스 이름에 Pickup/Loot/Chest/Emerald/Drop) → 클래스 이름
        self.quest_objs = {} # 퀘스트 상호작용 대상(QuestASCActor: 벌통 자리 같은 것, QuestCharacter: 퀘스트 NPC) → 클래스 이름
        self.guides = []     # GCN_ShowGuidance_C(왼쪽 스틱 누르면 생기는 안내 경로, SplineComponent에 세계 좌표 점)

    def _chain(self, c):
        r = self.chain.get(c)
        if r is None:
            r, x = [], c
            for _ in range(40):
                if not x:
                    break
                r.append(self.ue.objname(x))
                x = self.ue.q(x + 0x40)
            self.chain[c] = r
        return r

    def _off(self, o, name):
        c = self.ue.cls(o)
        k = (c, name)
        if k not in self.off:
            # 이미 사라진 객체(죽은 몹·주운 물건)는 클래스 자리에 쓰레기 값이 있어서, 그걸로 부모 클래스를 따라가면
            # 끝없이 돌 수 있음(10-22 11:25 봇 멈춤: uemem.supers 무한 반복). 훑을 때 본 진짜 클래스만 허용.
            if VALID_CLS and c not in VALID_CLS:
                raise ValueError("사라진 객체(클래스 모름)")
            self.off[k] = self.ue.field(o, name).offset
        return self.off[k]

    def scan(self):
        """객체 표를 한 번 훑어서 캐릭터·몹·속성 묶음 목록을 새로 만든다(약 1초)."""
        ue = self.ue
        player, mobs, npcs, atr, navpaths, trail, guides, quest, loot = None, {}, set(), {}, [], None, [], {}, {}
        for o in ue.iter_objects():
            try:
                VALID_CLS.add(ue.cls(o))
                ch = self._chain(ue.cls(o))
                n = ch[0] if ch else ""
                if n.startswith("ATR_"):
                    atr.setdefault(ue.outer(o), {})[n] = o
                    continue
                if n == "NavigationPath":
                    navpaths.append(o)
                    continue
                if n.startswith("GCN_ShowGuidance") and not ue.objname(o).startswith("Default__"):
                    guides.append(o)
                    continue
                if "GuidanceTrail" in n and not ue.objname(o).startswith("Default__"):
                    trail = o
                    continue
                if "QuestASCActor" in ch and not ue.objname(o).startswith("Default__"):
                    quest[o] = n
                    continue
                if any(k in n for k in LOOT) and "Actor" in ch and not n.startswith(LOOT_SKIP) \
                        and not ue.objname(o).startswith("Default__"):
                    loot[o] = n
                    continue
                if "Pawn" not in ch or ue.objname(o).startswith("Default__"):
                    continue
                if "PlayerCharacter" in ch:
                    player = o
                elif "QuestCharacter" in ch:
                    npcs.add(o)
                    quest[o] = n
                elif "MobCharacter" in ch:
                    mobs[o] = n
            except Exception:
                continue
        self.player, self.mobs, self.npcs, self.atr = player, mobs, npcs, atr
        self.navpaths, self.trail, self.guides, self.quest_objs = navpaths, trail, guides, quest
        self.loot = loot

    def spline(self, comp):
        """SplineComponent.SplineCurves.Position.Points(원소 88바이트: InVal float, OutVal FVector@+8) → 점 목록"""
        data, num, mx = struct.unpack("<Qii", self.ue.read(comp + self._off(comp, "SplineCurves"), 16))
        if not data or num <= 0 or num > 5000 or num > mx:
            return []
        raw = self.ue.read(data, num * 88)
        return [struct.unpack_from("<ddd", raw, i * 88 + 8) for i in range(num)]

    def points(self, o, field):
        """TArray<FVector> 필드 → [(x, y, z), ...]"""
        data, num, mx = struct.unpack("<Qii", self.ue.read(o + self._off(o, field), 16))
        if not data or num <= 0 or num > 2000 or num > mx:
            return []
        raw = self.ue.read(data, num * 24)
        return [struct.unpack_from("<ddd", raw, i * 24) for i in range(num)]

    def guide_path(self, me_xy, press_xy=None):
        """게임이 그린 안내 경로(GCN_ShowGuidance 스플라인) 중 하나를 고른다.
        press_xy(왼쪽 스틱을 누른 위치)가 있으면 그 자리에서 시작하는 경로 = 방금 새로 그린 경로를 고르고,
        없으면 내 위치에 가장 가까운 경로. 옛 경로·몹 경로(NavigationPath)는 쓰지 않는다."""
        best, best_d = None, 1e18
        for g in self.guides:
            try:
                sp = self.ue.q(g + self._off(g, "SplineComponent"))
                pts = self.spline(sp) if sp else []
            except Exception:
                continue
            if len(pts) < 2:
                continue
            if press_xy:
                d = ((pts[0][0] - press_xy[0]) ** 2 + (pts[0][1] - press_xy[1]) ** 2) ** 0.5
            else:
                d = min(((p[0] - me_xy[0]) ** 2 + (p[1] - me_xy[1]) ** 2) ** 0.5 for p in pts)
            if d < best_d:
                best, best_d = pts, d
        if best and best_d < (400 if press_xy else 1500):
            return best, "guide"
        if self.trail:
            try:
                pts = self.points(self.trail, "GuidanceLinePositions")
                if len(pts) >= 2 and min(((p[0] - me_xy[0]) ** 2 + (p[1] - me_xy[1]) ** 2) ** 0.5 for p in pts) < 1200:
                    return pts, "trail"
            except Exception:
                pass
        return None, None

    RENDER_OFF = 0x32c   # 몸통(Mesh) 부품의 LastRenderTimeOnScreen(occlusion_probe로 찾음, 0x328은 LastRenderTime)

    def render_age(self, o):
        """이 캐릭터가 화면에 마지막으로 그려진 뒤 지난 시간(초). 벽에 가려지거나 화면 밖이면 커진다."""
        ue = self.ue
        me_mesh = ue.q(self.player + self._off(self.player, "Mesh"))
        mesh = ue.q(o + self._off(o, "Mesh"))
        return ue.f32(me_mesh + self.RENDER_OFF) - ue.f32(mesh + self.RENDER_OFF)

    def loc(self, o):
        r = self.ue.q(o + self._off(o, "RootComponent"))
        return struct.unpack("<ddd", self.ue.read(r + self._off(r, "RelativeLocation"), 24))

    def yaw(self, o):
        r = self.ue.q(o + self._off(o, "RootComponent"))
        return struct.unpack("<ddd", self.ue.read(r + self._off(r, "RelativeRotation"), 24))[1]

    def vel(self, o):
        m = self.ue.q(o + self._off(o, "CharacterMovement"))
        return struct.unpack("<ddd", self.ue.read(m + self._off(m, "Velocity"), 24))

    def attr(self, o, set_name, field):
        a = self.atr.get(o, {}).get(set_name)
        if not a:
            return None
        return self.ue.f32(a + self._off(a, field) + 0xC)

    def hp(self, o):
        h, m = self.attr(o, "ATR_Health", "Health"), self.attr(o, "ATR_Health", "HealthMax")
        return h, m

    def dump_sets(self, o):
        """그 캐릭터의 ATR 묶음 숫자를 전부(기본/현재) 적는다."""
        for n, a in sorted(self.atr.get(o, {}).items()):
            log(f"  {n}")
            for name, p in sorted(self.ue.oprops(a).items(), key=lambda x: x[1].offset):
                try:
                    if p.kind == "StructProperty":
                        b, c = struct.unpack("<ff", self.ue.read(a + p.offset + 8, 8))
                        log(f"    {name}: {b:g} / {c:g}")
                    elif p.kind in ("FloatProperty", "IntProperty", "BoolProperty"):
                        log(f"    {name}: ({p.kind}) {self.ue.read(a + p.offset, 4).hex()}")
                except Exception:
                    log(f"    {name}: 읽기 실패")

    def snapshot(self):
        me = self.player
        s = {"t": round(time.time(), 2)}
        x, y, z = self.loc(me)
        s["me"] = {"pos": [round(x), round(y), round(z)], "yaw": round(self.yaw(me)),
                   "vel": [round(v) for v in self.vel(me)[:2]]}
        h, m = self.hp(me)
        s["me"]["hp"] = [round(h, 1) if h is not None else None, round(m, 1) if m is not None else None]
        for n, f in (("soul", "Souls"), ("soul_max", "SoulsMax")):
            s["me"][n] = self.attr(me, "ATR_Soul", f) if self._has(me, "ATR_Soul", f) else None
        mobs = []
        for o, n in list(self.mobs.items()):
            try:
                mx, my, mz = self.loc(o)
                h, m = self.hp(o)
                if h is not None and h <= 0:
                    continue
                d = ((mx - x) ** 2 + (my - y) ** 2) ** 0.5
                mobs.append({"cls": n, "d": round(d), "dx": round(mx - x), "dy": round(my - y),
                             "hp": [round(h, 1) if h is not None else None, round(m, 1) if m is not None else None]})
            except Exception:
                self.mobs.pop(o, None)   # 사라진 몹
        mobs.sort(key=lambda m: m["d"])
        s["mobs"] = mobs[:20]
        return s

    def _has(self, o, set_name, field):
        a = self.atr.get(o, {}).get(set_name)
        return bool(a) and field in self.ue.oprops(a)


def main():
    app = find_ohs_app()
    if not app:
        log("Offline Hero Sync 폴더를 못 찾았어.")
        return
    sys.path.insert(0, app)
    import winproc  # noqa
    import uemem    # noqa
    proc = winproc.Process()
    ue = uemem.UE(proc, rescan=True)
    r = Reader(ue)
    t = time.time()
    r.scan()
    log(f"훑기 {time.time() - t:.1f}초, 몹 {len(r.mobs)}마리, NPC {len(r.npcs)}명")
    if not r.player:
        log("내 캐릭터를 못 찾았어. 월드에 들어간 상태로 다시 해 줘.")
        return
    log(f"\n[내 캐릭터 속성 묶음] {ue.objname(r.player)}")
    r.dump_sets(r.player)

    log(f"\n[기록] {SECONDS:.0f}초 동안 초당 {HZ}번. 지금 몹이랑 싸우고 물약·유물 한 번씩 써 줘.")
    snaps, last_scan, t0 = [], time.time(), time.time()
    with open(LOG, "w", encoding="utf-8") as f:
        while time.time() - t0 < SECONDS:
            tick = time.time()
            if tick - last_scan > 2:
                r.scan()
                last_scan = tick
            try:
                s = r.snapshot()
            except Exception:
                log("읽기 실패:", traceback.format_exc(limit=1).strip().splitlines()[-1])
                time.sleep(0.5)
                continue
            snaps.append(s)
            f.write(json.dumps(s, ensure_ascii=False) + "\n")
            me = s["me"]
            near = s["mobs"][0] if s["mobs"] else None
            print(f"\r체력 {me['hp'][0]}/{me['hp'][1]}  영혼 {me['soul']}  몹 {len(s['mobs'])}  "
                  f"가까운 몹 {near['cls'] + ' ' + str(near['d']) if near else '-'}      ", end="", flush=True)
            time.sleep(max(0, 1 / HZ - (time.time() - tick)))
    print()

    log(f"\n[요약] 기록 {len(snaps)}개 (목표 {int(SECONDS * HZ)}개)")
    if snaps:
        hps = [s["me"]["hp"][0] for s in snaps if s["me"]["hp"][0] is not None]
        if hps:
            log(f"  내 체력 최저 {min(hps)} 최고 {max(hps)} (바뀐 횟수 {sum(a != b for a, b in zip(hps, hps[1:]))})")
        souls = [s["me"]["soul"] for s in snaps if s["me"]["soul"] is not None]
        if souls:
            log(f"  영혼 최저 {min(souls):.1f} 최고 {max(souls):.1f}")
        log(f"  몹 수 최소 {min(len(s['mobs']) for s in snaps)} 최대 {max(len(s['mobs']) for s in snaps)}")
        moved = sum(1 for a, b in zip(snaps, snaps[1:]) if a["me"]["pos"] != b["me"]["pos"])
        log(f"  내가 움직인 기록 {moved}개")
        for i in range(0, len(snaps), max(1, len(snaps) // 15)):
            s = snaps[i]
            m = s["mobs"][:3]
            log(f"  {s['t'] - snaps[0]['t']:5.1f}초 체력 {s['me']['hp'][0]} 영혼 {s['me']['soul']} 위치 {s['me']['pos']} "
                f"속도 {s['me']['vel']} | " + ", ".join(f"{x['cls']} {x['d']} hp{x['hp'][0]}" for x in m))
    # 처음 몹 하나의 속성 묶음(적 체력 확인용)
    if r.mobs:
        o = next(iter(r.mobs))
        log(f"\n[몹 하나 속성 묶음 이름] {r.mobs[o]}: {', '.join(sorted(r.atr.get(o, {})))}")


if __name__ == "__main__":
    sys.path.insert(0, HERE)
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
    print("이 폴더에 생긴 state_reader.txt를 디스코드로 보내 줘.")
