"""어떤 클래스의 객체를 전부 위치·지정한 값과 함께 적기(읽기만 함). 결과 class_probe.txt.
사용: python class_probe.py BP_MinecartStation_C NameOnMap,bUnlocked,bStartAsUnlocked [다른클래스 필드,...]
(클래스·필드 이름은 catalog_schema.txt에서 고른다)
"""
from __future__ import annotations

import math
import os
import struct
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "class_probe.txt")
sys.path.insert(0, HERE)
from state_probe import find_ohs_app  # noqa: E402

lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


def main():
    args = sys.argv[1:]
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
    log("내 위치", tuple(round(v) for v in me))
    for i in range(0, len(args), 2):
        cname = args[i]
        names = args[i + 1].split(",") if i + 1 < len(args) else []
        objs = [o for o in ue.find_instances(cname) if not ue.objname(o).startswith("Default__")]
        log(f"\n##### {cname}: {len(objs)}개")
        rows = []
        for o in objs:
            try:
                props = ue.oprops(o)
                p = None
                if "RootComponent" in props:
                    rc = ue.q(o + props["RootComponent"].offset)
                    if rc:
                        p = struct.unpack("<ddd", ue.read(rc + ue.field(rc, "RelativeLocation").offset, 24))
                vals = {n: value(ue, o, props[n])[:100] for n in names if n in props}
                d = math.hypot(p[0] - me[0], p[1] - me[1]) if p else -1
                rows.append((d, tuple(round(v) for v in p) if p else None, vals, ue.objname(o)[:60]))
            except Exception as e:
                rows.append((-2, None, {"err": str(e)[:60]}, ""))
        for d, p, vals, n in sorted(rows, key=lambda x: x[0]):
            log(f"  {d:8.0f}  {p}  {vals}  {n}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
