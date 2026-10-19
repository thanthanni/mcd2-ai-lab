"""길 안내선·퀘스트 목표 위치 찾기(읽기만 함).

게임에서 왼쪽 스틱을 눌러 길 안내선(빛나는 줄)을 켠 상태로 실행한다.
안내선·경로 따라가기·퀘스트 마커 관련 객체의 속성 값을 guide_probe.txt에 적는다.
"""
from __future__ import annotations

import os
import struct
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "guide_probe.txt")
sys.path.insert(0, HERE)
from state_probe import find_ohs_app  # noqa: E402

KEYS = ("GuidanceTrail", "PathFollowing", "QuestObjective", "Marker_Quest", "QuestTracker",
        "Waypoint", "Objective", "Spline", "Navigation", "Destination")
lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


def value(ue, o, p):
    a = o + p.offset
    k = p.kind
    try:
        if k == "FloatProperty":
            return f"{ue.f32(a):g}"
        if k == "DoubleProperty":
            return f"{ue.f64(a):g}"
        if k in ("IntProperty", "UInt32Property"):
            return str(ue.i32(a))
        if k in ("ByteProperty", "BoolProperty", "EnumProperty"):
            return ue.read(a, 1).hex()
        if k == "NameProperty":
            return ue.fname(a)
        if k == "StrProperty":
            return repr(ue.fstring(a))
        if k in ("ObjectProperty", "WeakObjectProperty", "ClassProperty"):
            if k == "WeakObjectProperty":
                return "(weak) " + ue.read(a, 8).hex()
            x = ue.q(a)
            return ue.clsname(x) + " " + ue.objname(x) if x else "없음"
        if k == "StructProperty":
            sn = ue.objname(p.struct)
            if sn in ("Vector", "Vector_NetQuantize", "Vector_NetQuantize100"):
                return sn + " " + str(tuple(round(v) for v in struct.unpack("<ddd", ue.read(a, 24))))
            if sn == "Vector2D":
                return sn + " " + str(struct.unpack("<dd", ue.read(a, 16)))
            return sn + " " + ue.read(a, min(p.size, 32)).hex()
        if k == "ArrayProperty":
            data, num, mx = struct.unpack("<Qii", ue.read(a, 16))
            inner = p.inner
            desc = inner.kind
            if inner.kind == "StructProperty":
                desc += ":" + ue.objname(inner.struct)
            s = f"[{num}개 {desc}, 원소 {inner.size}바이트]"
            if 0 < num < 100000 and data:
                for i in range(min(num, 6)):
                    e = data + i * inner.size
                    if inner.kind == "StructProperty" and ue.objname(inner.struct) == "Vector":
                        s += " " + str(tuple(round(v) for v in struct.unpack("<ddd", ue.read(e, 24))))
                    elif inner.kind == "ObjectProperty":
                        x = ue.q(e)
                        s += " " + (ue.objname(x) if x else "없음")
                    else:
                        s += " " + ue.read(e, min(inner.size, 48)).hex()
            return s
        return ue.read(a, min(max(p.size, 1), 16)).hex()
    except Exception as e:
        return f"(읽기 실패 {e})"


def dump(ue, o, skip_engine=True):
    log(f"\n== {ue.fullname(o)}")
    actor = skip_engine and ue.is_a(o, "Actor")
    for name, p in sorted(ue.oprops(o).items(), key=lambda x: x[1].offset):
        if "Delegate" in p.kind:
            continue
        if actor and p.offset < 0x2b0:
            continue   # Actor 공통 속성은 생략
        log(f"  +{p.offset:#06x} {p.kind:20s} {name} = {value(ue, o, p)}")


def main():
    app = find_ohs_app()
    if not app:
        log("Offline Hero Sync 폴더를 못 찾았어.")
        return
    sys.path.insert(0, app)
    import winproc  # noqa
    import uemem    # noqa
    ue = uemem.UE(winproc.Process(), rescan=True)
    found = {}
    me = None
    for o in ue.iter_objects():
        try:
            n = ue.clsname(o)
            if ue.objname(o).startswith("Default__"):
                continue
            if n == "BP_AlexCharacter_C" or (me is None and ue.is_a(o, "PlayerCharacter")):
                me = o
            if any(k in n for k in KEYS) and not n.startswith(("W_", "AS_", "Mock")):
                found.setdefault(n, []).append(o)
        except Exception:
            continue
    log("[찾은 클래스]")
    for n, objs in sorted(found.items()):
        log(f"  {n}: {len(objs)}개")
    if me:
        r = ue.q(me + ue.field(me, "RootComponent").offset)
        loc = struct.unpack("<ddd", ue.read(r + ue.field(r, "RelativeLocation").offset, 24))
        log(f"\n내 위치: {tuple(round(v) for v in loc)}")
    for n, objs in sorted(found.items()):
        if n.startswith(("BTTask", "BTDecorator", "EnvQuery", "NavArea", "Interchange", "Niagara", "MovieScene")):
            continue
        cnt = 0
        for o in objs:
            if cnt >= 3:
                break
            try:
                dump(ue, o)
                cnt += 1
            except Exception:
                log(f"  {n} 읽기 실패")
    # 안내선 액터의 부품(Spline 등)도 적기
    for n, objs in found.items():
        if "GuidanceTrail" not in n:
            continue
        for trail in objs[:2]:
            for o in ue.iter_objects():
                try:
                    if ue.outer(o) == trail:
                        dump(ue, o, skip_engine=False)
                except Exception:
                    continue


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
    print("이 폴더에 생긴 guide_probe.txt를 디스코드로 보내 줘.")
