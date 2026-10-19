"""내 주변 액터 전부 적기(읽기만 함). 퀘스트 대상(벌통 짓는 자리 같은 것)의 클래스 이름을 찾는 용도.

상호작용 대상 바로 옆(화면에 마름모 표시가 보이는 곳)에 서서 실행. 1500 안의 액터를 가까운 순으로,
가까운 10개는 속성 값까지 적는다.
"""
from __future__ import annotations

import math
import os
import struct
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "nearby_probe.txt")
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
    log("내 위치:", tuple(round(v) for v in me))
    hits, chain = [], {}
    for o in ue.iter_objects():
        try:
            c = ue.cls(o)
            if c not in chain:
                chain[c] = [ue.objname(x) for x in ue.supers(c)]
            if "Actor" not in chain[c] or ue.objname(o).startswith("Default__"):
                continue
            rc = ue.q(o + ue.field(o, "RootComponent").offset)
            if not rc:
                continue
            p = struct.unpack("<ddd", ue.read(rc + ue.field(rc, "RelativeLocation").offset, 24))
            d = math.dist(p, me)
            if d < 1500:
                hits.append((d, chain[c][0], " > ".join(chain[c][1:4]), p, o))
        except Exception:
            continue
    hits.sort(key=lambda h: h[0])
    log(f"\n[1500 안 액터 {len(hits)}개] 거리 / 클래스 / 상위 / 위치")
    for d, n, sup, p, o in hits:
        log(f"  {d:6.0f}  {n}  ({sup})  {tuple(round(v) for v in p)}")
    log("\n[가까운 10개 속성]")
    skip = ("BP_AlexCharacter_C", "BP_PlayerLight_C", "BP_PlayerLantern_C", "BP_InteractiveGrassHandler_C")
    shown = 0
    for d, n, sup, p, o in hits:
        if n in skip or "Character" in n:
            continue
        log(f"\n== {n} 거리 {d:.0f}")
        for name, pr in sorted(ue.oprops(o).items(), key=lambda x: x[1].offset):
            if pr.offset < 0x2b0 or "Delegate" in pr.kind:
                continue
            log(f"  +{pr.offset:#06x} {pr.kind:18s} {name} = {value(ue, o, pr)}")
        shown += 1
        if shown >= 10:
            break


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
