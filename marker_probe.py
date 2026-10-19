"""퀘스트 목표 위치를 메모리에서 직접 찾기(읽기만 함). 안내선(퀘스트 추적) 없이도 목표로 가기 위해.

미니맵·지도에 퀘스트 표시가 뜨니까 그 표시의 세계 좌표가 어딘가에 있다. 이름에 Marker·Objective·Waypoint·
Tracked·QuestProgress·MapIcon·POI가 들어간 객체(위젯 포함)의 속성 중 좌표(Vector)·퀘스트 이름·배열을 적는다.
"""
from __future__ import annotations

import math
import os
import struct
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "marker_probe.txt")
sys.path.insert(0, HERE)
from state_probe import find_ohs_app  # noqa: E402

KEYS = ("Marker", "Objective", "Waypoint", "Tracked", "QuestProgress", "MapIcon", "POI", "QuestTracker",
        "ActiveQuest", "QuestSubsystem", "QuestLog", "QuestJournal")
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
    found = {}
    for o in ue.iter_objects():
        try:
            n = ue.clsname(o)
            if any(k in n for k in KEYS) and not ue.objname(o).startswith("Default__"):
                found.setdefault(n, []).append(o)
        except Exception:
            continue
    log("[찾은 클래스]", {n: len(v) for n, v in sorted(found.items())})
    for n, objs in sorted(found.items()):
        for o in objs[:4]:
            props = sorted(ue.oprops(o).items(), key=lambda x: x[1].offset)
            keep = []
            for name, p in props:
                if "Delegate" in p.kind or p.kind == "BoolProperty":
                    continue
                v = value(ue, o, p)
                interesting = ("Vector" in v or p.kind in ("ArrayProperty", "MapProperty", "SetProperty", "NameProperty",
                                                          "StrProperty", "TextProperty", "ObjectProperty", "StructProperty"))
                if interesting and not v.startswith("[0개") and v != "없음":
                    keep.append(f"  +{p.offset:#06x} {p.kind:18s} {name} = {v[:200]}")
            if keep:
                log(f"\n== {n} {ue.objname(o)[:70]}")
                for k in keep[:40]:
                    log(k)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
