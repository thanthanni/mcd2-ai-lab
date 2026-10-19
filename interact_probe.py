"""퀘스트 상호작용 대상 찾기(읽기만 함).

안내선이 없는 '상호작용 구간'에서 실행. 이름에 Quest·Objective·Interact·Prompt·Marker·Lever·Chest·Pickup이
들어간 객체 중 위치가 있는 것(액터·부품)을 내 위치에서 가까운 순으로 적고, 가까운 몇 개는 속성 값도 적는다.
"""
from __future__ import annotations

import math
import os
import struct
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "interact_probe.txt")
sys.path.insert(0, HERE)
from state_probe import find_ohs_app  # noqa: E402

KEYS = ("Quest", "Objective", "Interact", "Prompt", "Marker", "Lever", "Chest", "Pickup", "Button", "Door", "Gate")
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

    def where(o):
        """액터면 RootComponent 위치, 부품이면 자기 RelativeLocation(부모 기준일 수 있음)."""
        props = ue.oprops(o)
        if "RootComponent" in props:
            rc = ue.q(o + props["RootComponent"].offset)
            if rc:
                return struct.unpack("<ddd", ue.read(rc + ue.field(rc, "RelativeLocation").offset, 24)), "actor"
        if "RelativeLocation" in props:
            return struct.unpack("<ddd", ue.read(o + props["RelativeLocation"].offset, 24)), "comp"
        return None, None

    hits = []
    for o in ue.iter_objects():
        try:
            n = ue.clsname(o)
            if not any(k in n for k in KEYS) or n.startswith(("W_", "AS_", "Mock", "BTTask", "GA_", "GE_", "GCN_")):
                continue
            if ue.objname(o).startswith("Default__"):
                continue
            p, kind = where(o)
            if not p or not all(math.isfinite(v) for v in p):
                continue
            d = math.hypot(p[0] - me[0], p[1] - me[1])
            outer = ue.objname(ue.outer(o)) if ue.outer(o) else ""
            hits.append((d, n, kind, p, outer, o))
        except Exception:
            continue
    hits.sort(key=lambda h: h[0])
    log(f"\n[가까운 순 {min(len(hits), 60)}개 / 전체 {len(hits)}개] 거리 / 클래스 / 종류 / 위치 / 주인")
    for d, n, kind, p, outer, o in hits[:60]:
        log(f"  {d:7.0f}  {n}  {kind}  {tuple(round(v) for v in p)}  {outer[:60]}")
    log("\n[가까운 액터 8개 속성]")
    shown = 0
    for d, n, kind, p, outer, o in hits:
        if kind != "actor" or d > 3000:
            continue
        log(f"\n== {n} 거리 {d:.0f}")
        for name, pr in sorted(ue.oprops(o).items(), key=lambda x: x[1].offset):
            if pr.offset < 0x2b0 or "Delegate" in pr.kind:
                continue
            log(f"  +{pr.offset:#06x} {pr.kind:18s} {name} = {value(ue, o, pr)}")
        shown += 1
        if shown >= 8:
            break


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
