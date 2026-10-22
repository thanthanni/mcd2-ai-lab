"""퀘스트 목적지·상호작용 대상이 맵 어디 있는지 찾기(읽기만 함). 결과 dest_probe.txt.

퀘스트 목표의 TargetDestination('CA05_E20_Destination')·InteractionTarget('CA05_I18_Target') 같은 이름이
① 객체 이름 ② 액터 Tags(이름 배열) ③ 문자열 속성 값 중 어디에 쓰여 있는지 찾고, 찾으면 위치를 적는다.
인자로 찾을 조각을 줄 수 있음(기본: CA05).
"""
from __future__ import annotations

import math
import os
import struct
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "dest_probe.txt")
sys.path.insert(0, HERE)
from state_probe import find_ohs_app  # noqa: E402

lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


def main():
    key = sys.argv[1] if len(sys.argv) > 1 else "CA05"
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
    log(f"찾는 조각: {key}  내 위치 {tuple(round(v) for v in me)}")

    def where(o):
        props = ue.oprops(o)
        if "RootComponent" in props:
            rc = ue.q(o + props["RootComponent"].offset)
            if rc:
                return struct.unpack("<ddd", ue.read(rc + ue.field(rc, "RelativeLocation").offset, 24))
        return None

    hits = []
    for o in ue.iter_objects():
        try:
            name = ue.objname(o)
            if name.startswith("Default__"):
                continue
            how = None
            if key in name:
                how = "이름"
            props = ue.oprops(o)
            if not how and "Tags" in props:              # 액터 태그(FName 배열)
                data, num, mx = struct.unpack("<Qii", ue.read(o + props["Tags"].offset, 16))
                if data and 0 < num < 50:
                    tags = [ue.fname(data + i * 8) for i in range(num)]
                    if any(key in t for t in tags):
                        how = "태그 " + ",".join(tags)[:120]
            if not how:
                for pn, pr in props.items():
                    if pr.kind in ("StrProperty", "NameProperty") and pr.offset >= 0x28:
                        try:
                            v = ue.fstring(o + pr.offset) if pr.kind == "StrProperty" else ue.fname(o + pr.offset)
                        except Exception:
                            continue
                        if v and key in v:
                            how = f"속성 {pn}={v[:80]}"
                            break
            if how:
                p = where(o)
                d = math.hypot(p[0] - me[0], p[1] - me[1]) if p else -1
                hits.append((ue.clsname(o), name[:70], how, tuple(round(v) for v in p) if p else None, round(d)))
        except Exception:
            continue
    log(f"찾은 것 {len(hits)}개")
    for h in sorted(hits, key=lambda x: (x[3] is None, x[1]))[:300]:
        log("  ", " | ".join(str(x) for x in h))


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
