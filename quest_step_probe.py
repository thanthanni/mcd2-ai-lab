"""조사(10-24): 추적 중인 퀘스트(기본 CA05)의 단계 나무를 상태와 함께 적고, 진행 중(State 01) 단계의 목표 이름
(TargetDestination·InteractionTarget)과 이름이 맞는 객체를 메모리 전체에서 찾아 위치를 적는다. 조작 없음.
결과 quest_step_probe.txt"""
from __future__ import annotations

import math
import os
import struct
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, "quest_step_probe.txt")
QID = sys.argv[1] if len(sys.argv) > 1 else "CA05"
lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def main():
    from state_probe import find_ohs_app
    sys.path.insert(0, find_ohs_app())
    import winproc  # noqa
    import uemem    # noqa
    from state_reader import Reader
    ue = uemem.UE(winproc.Process(), rescan=True)
    r = Reader(ue)
    r.scan()
    me = r.loc(r.player)
    log(f"내 위치 {tuple(round(v) for v in me)}")

    def sval(o, name):
        pr = ue.oprops(o)
        if name not in pr:
            return None
        p = pr[name]
        a = o + p.offset
        if p.kind == "StrProperty":
            return ue.fstring(a)
        if p.kind == "NameProperty":
            return ue.fname(a)
        if p.kind == "StructProperty":
            sn = ue.objname(p.struct)
            if sn == "GameplayTag":
                return "#" + ue.fname(a)
            sp = ue.props(p.struct)
            if "State" in sp:
                return ue.read(a + sp["State"].offset, 1).hex()
            return sn
        if p.kind in ("ByteProperty", "EnumProperty", "BoolProperty"):
            return ue.read(a, 1).hex()
        if p.kind == "IntProperty":
            return ue.i32(a)
        return p.kind

    # 1) 객체 한 번 훑기: LiveQuest 찾기 + 이름 목록(나중에 목표 이름과 맞춰 봄)
    quests, named = [], []
    t0 = time.time()
    for o in ue.iter_objects():
        if time.time() - t0 > 90:
            log("(훑기 90초 넘음)")
            break
        try:
            n = ue.objname(o)
            if n.startswith("Default__"):
                continue
            c = ue.clsname(o)
            if c == "LiveQuest":
                quests.append(o)
            elif QID in n or "Destination" in c or "Destination" in n:
                named.append(o)
        except Exception:
            continue
    log(f"LiveQuest {len(quests)}개, 이름에 {QID}/Destination 들어간 객체 {len(named)}개 ({time.time() - t0:.0f}초)")

    targets = []

    def tree(t, depth):
        pr = ue.oprops(t)
        tid, st = sval(t, "ID"), sval(t, "State")
        info = f"{ue.clsname(t)} {tid} 상태 {st}"
        if "ReferenceGoal" in pr:
            g = ue.q(t + pr["ReferenceGoal"].offset)
            if g:
                for k in ("Comment", "TargetDestination", "InteractionTarget", "NPCTag", "HowMany"):
                    v = sval(g, k)
                    if v not in (None, "", "''"):
                        info += f" {k}={v}"
                        if k in ("TargetDestination", "InteractionTarget") and st == "01":
                            targets.append(str(v).strip("'"))
        log("  " * depth + "- " + info)
        if "Tasks" in pr and pr["Tasks"].kind == "ArrayProperty" and depth < 6:
            data, num, mx = struct.unpack("<Qii", ue.read(t + pr["Tasks"].offset, 16))
            for i in range(min(num, 60) if data and 0 < num < 1000 else 0):
                c = ue.q(data + i * 8)
                if c:
                    tree(c, depth + 1)

    for q in quests:
        try:
            if sval(q, "ID") != QID:
                continue
            log(f"\n[퀘스트 {QID}] 상태 {sval(q, 'State')}")
            pr = ue.oprops(q)
            t = ue.q(q + pr["Tasks"].offset)
            if t:
                tree(t, 1)
        except Exception:
            log("  읽기 실패:", traceback.format_exc(limit=1).strip().splitlines()[-1])
    log(f"\n[진행 중 단계의 목표 이름] {targets}")

    log("\n[이름이 맞는 객체(가까운 순)]")
    rows = []
    for o in named:
        try:
            n = ue.objname(o)
            hit = any(tg and tg.split("_Destination")[0].split("_Target")[0] in n for tg in targets)
            try:
                p = r.loc(o)
                d = math.dist(p[:2], me[:2])
            except Exception:
                p, d = None, 1e12
            rows.append((0 if hit else 1, d, ue.clsname(o), n, p))
        except Exception:
            continue
    rows.sort(key=lambda x: (x[0], x[1]))
    for hit, d, c, n, p in rows[:60]:
        log(f"  {'★' if hit == 0 else ' '} {d:9.0f} {c} {n[:70]} {tuple(round(v) for v in p) if p else '(위치 없음)'}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
