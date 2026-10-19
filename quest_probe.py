"""지금 진행 중인(상호작용해야 하는) 퀘스트 대상 구별하기(읽기만 함).

퀘스트 대상(QuestASCActor·QuestCharacter)마다: 거리, 퀘스트 표시 파티클(NS_QuestIdleParticle) 켜짐 여부,
QuestActorBehaviourComponent 속성 값을 적는다. 켜진 것 = 마름모 표시가 뜬 대상일 가능성이 크다.
"""
from __future__ import annotations

import math
import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "quest_probe.txt")
sys.path.insert(0, HERE)
from state_probe import find_ohs_app  # noqa: E402

lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


def main():
    app = find_ohs_app()
    if not app:
        log("Offline Hero Sync 폴더를 못 찾았어.")
        return
    sys.path.insert(0, app)
    import winproc  # noqa
    import uemem    # noqa
    from state_reader import Reader
    from guide_probe import value
    ue = uemem.UE(winproc.Process(), rescan=True)
    r = Reader(ue)
    r.scan()
    me = r.loc(r.player)
    log("내 위치:", tuple(round(v) for v in me), " 퀘스트 대상", len(r.quest_objs))

    def flag(o, name):
        p = ue.field(o, name)
        off, mask = p.bool_mask
        return 1 if ue.u8(o + p.offset + off) & mask else 0

    rows = []
    for o, n in r.quest_objs.items():
        try:
            p = r.loc(o)
            d = math.hypot(p[0] - me[0], p[1] - me[1])
            info = {}
            props = ue.oprops(o)
            for cname in ("NS_QuestIdleParticle", "Niagara"):
                if cname in props:
                    c = ue.q(o + props[cname].offset)
                    if c:
                        info[cname] = f"active={flag(c, 'bIsActive')} visible={flag(c, 'bVisible')} hidden={flag(c, 'bHiddenInGame')}"
            info["actorHidden"] = flag(o, "bHidden")
            rows.append((d, n, info, o))
        except Exception as e:
            rows.append((1e9, n, {"err": str(e)[:60]}, o))
    rows.sort(key=lambda x: x[0])
    log("\n[퀘스트 대상] 거리 / 이름 / 표시 상태")
    for d, n, info, o in rows[:60]:
        log(f"  {d:7.0f}  {n}  {info}")
    log("\n[가까운 5개의 QuestActorBehaviourComponent]")
    k = 0
    for d, n, info, o in rows:
        props = ue.oprops(o)
        if "QuestActorBehaviourComponent" not in props:
            continue
        c = ue.q(o + props["QuestActorBehaviourComponent"].offset)
        if not c:
            continue
        log(f"\n== {n} 거리 {d:.0f}")
        for name, pr in sorted(ue.oprops(c).items(), key=lambda x: x[1].offset):
            if pr.offset < 0xb0 or "Delegate" in pr.kind:
                continue
            log(f"  +{pr.offset:#06x} {pr.kind:18s} {name} = {value(ue, c, pr)[:160]}")
        k += 1
        if k >= 5:
            break


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
