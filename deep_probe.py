"""클래스 이름(인자)의 객체를 안쪽 구조체·배열까지 펼쳐 적는다(읽기만 함). 결과 deep_probe.txt.
사용: python deep_probe.py BP_QuestRunner_C [다른 클래스 ...]"""
from __future__ import annotations

import math
import os
import struct
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "deep_probe.txt")
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
    ue = uemem.UE(winproc.Process(), rescan=True)
    r = Reader(ue)
    r.scan()
    me = r.loc(r.player)
    log("내 위치:", tuple(round(v) for v in me))

    def leaf(a, p):
        k = p.kind
        try:
            if k == "FloatProperty":
                return f"{ue.f32(a):g}"
            if k == "DoubleProperty":
                return f"{ue.f64(a):g}"
            if k in ("IntProperty", "UInt32Property"):
                return str(ue.i32(a))
            if k in ("ByteProperty", "EnumProperty", "BoolProperty"):
                return ue.read(a, 1).hex()
            if k == "NameProperty":
                return ue.fname(a)
            if k == "StrProperty":
                return repr(ue.fstring(a))
            if k in ("ObjectProperty", "ClassProperty"):
                x = ue.q(a)
                return (ue.clsname(x) + " " + ue.objname(x)) if x else "없음"
            if k == "WeakObjectProperty":
                return "(weak)"
            return ue.read(a, min(max(p.size, 1), 16)).hex()
        except Exception as e:
            return f"(실패 {e})"

    def dump(a, ustruct, depth, prefix, budget):
        """구조체 ustruct가 주소 a에 있을 때 필드를 펼쳐 적는다."""
        for name, p in sorted(ue.props(ustruct).items(), key=lambda x: x[1].offset):
            if budget[0] <= 0:
                return
            fa = a + p.offset
            if "Delegate" in p.kind:
                continue
            if p.kind == "StructProperty":
                sn = ue.objname(p.struct)
                if sn in ("Vector", "Vector_NetQuantize", "Vector_NetQuantize100"):
                    v = struct.unpack("<ddd", ue.read(fa, 24))
                    d = math.hypot(v[0] - me[0], v[1] - me[1])
                    log(f"{prefix}{name}: Vector {tuple(round(x) for x in v)} (나와 거리 {d:.0f})")
                    budget[0] -= 1
                elif sn == "GameplayTag":
                    log(f"{prefix}{name}: 태그 {ue.fname(fa)}")
                    budget[0] -= 1
                elif depth < 4:
                    log(f"{prefix}{name}: {sn}")
                    dump(fa, p.struct, depth + 1, prefix + "  ", budget)
            elif p.kind == "ArrayProperty":
                data, num, mx = struct.unpack("<Qii", ue.read(fa, 16))
                inner = p.inner
                desc = inner.kind + (":" + ue.objname(inner.struct) if inner.kind == "StructProperty" else "")
                log(f"{prefix}{name}: [{num}개 {desc}]")
                budget[0] -= 1
                if 0 < num < 100000 and data and depth < 4:
                    for i in range(min(num, 6)):
                        e = data + i * inner.size
                        if inner.kind == "StructProperty":
                            log(f"{prefix}  [{i}]")
                            dump(e, inner.struct, depth + 1, prefix + "    ", budget)
                        else:
                            log(f"{prefix}  [{i}] {leaf(e, inner)}")
            else:
                log(f"{prefix}{name}: {leaf(fa, p)}")
                budget[0] -= 1

    for arg in sys.argv[1:]:
        # "클래스:개수:줄수" 형식(기본 3개, 400줄). UObject 기본 칸(+0x28 앞)은 건너뜀
        parts = arg.split(":")
        cname = parts[0]
        nobj = int(parts[1]) if len(parts) > 1 else 3
        nline = int(parts[2]) if len(parts) > 2 else 400
        objs = ue.find_instances(cname)
        log(f"\n##### {cname}: {len(objs)}개")
        for o in objs[:nobj]:
            log(f"\n== {cname} {ue.objname(o)}")
            try:
                dump(o, ue.cls(o), 0, "  ", [nline])
            except Exception:
                log("  읽기 실패:", traceback.format_exc(limit=1).strip().splitlines()[-1])

if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
