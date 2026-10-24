"""조사(10-24): 클래스 이름에 인자 조각이 들어간 액터(기본: Gate, Gimmick)의 반사 속성을 얕게 다 적는다(읽기만).
결과 gimmick_probe.txt"""
from __future__ import annotations

import math
import os
import struct
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
OUT = os.path.join(HERE, "gimmick_probe.txt")
KEYS = sys.argv[1:] or ["DesertGate", "OutpostGate"]
R = 5000
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
    log(f"내 위치 {tuple(round(v) for v in me)} 찾는 조각 {KEYS}")

    def val(a, p, depth=0):
        k = p.kind
        try:
            if k == "BoolProperty":
                return ue.read(a, 1).hex()
            if k in ("ByteProperty", "EnumProperty"):
                return ue.read(a, 1).hex()
            if k == "IntProperty":
                return str(ue.i32(a))
            if k == "FloatProperty":
                return f"{ue.f32(a):g}"
            if k == "DoubleProperty":
                return f"{struct.unpack('<d', ue.read(a, 8))[0]:g}"
            if k == "NameProperty":
                return ue.fname(a)
            if k == "StrProperty":
                return repr(ue.fstring(a))
            if k in ("ObjectProperty", "WeakObjectProperty", "ClassProperty"):
                x = ue.q(a)
                return f"{ue.clsname(x)}:{ue.objname(x)[:40]}" if x and k != "WeakObjectProperty" else ("있음" if x else "없음")
            if k == "StructProperty":
                sn = ue.objname(p.struct)
                if sn == "GameplayTag":
                    return "#" + ue.fname(a)
                if sn == "GameplayTagContainer":
                    data, num, mx = struct.unpack("<Qii", ue.read(a, 16))
                    if data and 0 < num < 50:
                        return "[" + ", ".join("#" + ue.fname(data + i * 8) for i in range(num)) + "]"
                    return "[]"
                if sn in ("Vector", "Rotator"):
                    return str(tuple(round(v) for v in struct.unpack("<ddd", ue.read(a, 24))))
                if depth < 1:
                    parts = []
                    for n, q in sorted(ue.props(p.struct).items(), key=lambda x: x[1].offset):
                        if "Delegate" not in q.kind:
                            parts.append(f"{n}={val(a + q.offset, q, depth + 1)}")
                    return sn + "{" + ", ".join(parts)[:300] + "}"
                return sn
            if k == "ArrayProperty":
                data, num, mx = struct.unpack("<Qii", ue.read(a, 16))
                return f"[{num}개]" if 0 <= num < 100000 else "[?]"
            return k
        except Exception as e:
            return f"(실패 {str(e)[:20]})"

    t0, hits = time.time(), []
    for o in ue.iter_objects():
        if time.time() - t0 > 60:
            break
        try:
            n = ue.objname(o)
            if n.startswith("Default__"):
                continue
            c = ue.clsname(o)
            if not any(k in c or k in n for k in KEYS):
                continue
            try:
                p = r.loc(o)
            except Exception:
                continue
            if math.dist(p[:2], me[:2]) < R:
                hits.append((math.dist(p[:2], me[:2]), o, c, n, p))
        except Exception:
            continue
    hits.sort(key=lambda h: h[0])
    for d, o, c, n, p in hits[:6]:
        log(f"\n==== {c} {n[:70]} {tuple(round(v) for v in p)} 거리 {d:.0f}")
        props = ue.oprops(o)
        for name, q in sorted(props.items(), key=lambda x: x[1].offset):
            if "Delegate" in q.kind or name in ("RootComponent",):
                continue
            log(f"  {name} ({q.kind}) = {val(o + q.offset, q)}")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
