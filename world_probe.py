"""맵에 박힌 '특별한 자리' 찾기(읽기만 함): 점프로 건너는 자리(내비 링크), 물·위험 구역, 내비메시.

클래스 이름이나 부모 클래스 이름에 아래 낱말이 들어간 객체를 종류별로 세고, 가까운 순으로 위치를 적는다.
점프 링크가 있으면 처음 3개는 속성 값(양 끝 좌표 등)까지 적는다. 결과 world_probe.txt.
"""
from __future__ import annotations

import math
import os
import struct
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "world_probe.txt")
sys.path.insert(0, HERE)
from state_probe import find_ohs_app  # noqa: E402

KINDS = {
    "점프·이동 링크": ("NavLink", "SmartLink", "Jump", "Launch", "Traversal", "Ledge", "Climb", "Vault", "Leap"),
    "물·위험 구역": ("Water", "Fluid", "Swim", "PhysicsVolume", "PainCausing", "KillZ", "Kill", "Death", "Drown",
                 "Lava", "Hazard", "Damage"),
    "내비메시": ("RecastNavMesh", "NavMesh", "NavigationData", "NavModifier", "NavArea"),
}
SKIP = ("W_", "GA_", "GE_", "GCN_", "AS_", "BTTask", "BTService", "BTDecorator", "ABP_", "AM_", "DT_", "GameplayCue")

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
        props = ue.oprops(o)
        if "RootComponent" in props:
            rc = ue.q(o + props["RootComponent"].offset)
            if rc:
                return struct.unpack("<ddd", ue.read(rc + ue.field(rc, "RelativeLocation").offset, 24))
        if "RelativeLocation" in props:            # 부품: 주인 액터 위치를 씀(자기 위치는 주인 기준일 수 있음)
            owner = ue.outer(o)
            if owner and owner != o:
                p = where(owner)
                if p:
                    return p
            return struct.unpack("<ddd", ue.read(o + props["RelativeLocation"].offset, 24))
        return None

    found = {k: [] for k in KINDS}
    classes = {k: {} for k in KINDS}
    for o in ue.iter_objects():
        try:
            if ue.objname(o).startswith("Default__"):
                continue
            chain = r._chain(ue.cls(o))
            n = chain[0] if chain else ""
            if not n or n.startswith(SKIP):
                continue
            for kind, keys in KINDS.items():
                if any(any(k in c for k in keys) for c in chain[:4]):
                    classes[kind][n] = classes[kind].get(n, 0) + 1
                    p = where(o)
                    d = math.hypot(p[0] - me[0], p[1] - me[1]) if p and all(math.isfinite(v) for v in p) else 1e9
                    found[kind].append((d, n, " > ".join(chain[1:4]), p, o))
                    break
        except Exception:
            continue

    for kind in KINDS:
        log(f"\n##### {kind}: 객체 {len(found[kind])}개, 클래스 {len(classes[kind])}종")
        for n, c in sorted(classes[kind].items(), key=lambda x: -x[1])[:40]:
            log(f"  {c:5d}  {n}")
        log(f"  [가까운 순 20개] 거리 / 클래스 / 부모 / 위치")
        for d, n, par, p, o in sorted(found[kind], key=lambda x: x[0])[:20]:
            pos = tuple(round(v) for v in p) if p else "?"
            log(f"  {d:8.0f}  {n}  ({par})  {pos}")

    log("\n##### 점프·이동 링크 처음 3개 속성")
    for d, n, par, p, o in sorted(found["점프·이동 링크"], key=lambda x: x[0])[:3]:
        log(f"\n== {n} 거리 {d:.0f}")
        for name, pr in sorted(ue.oprops(o).items(), key=lambda x: x[1].offset):
            if "Delegate" in pr.kind:
                continue
            log(f"  +{pr.offset:#06x} {pr.kind:18s} {name} = {value(ue, o, pr)[:160]}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
