"""퀘스트 44개 전부 펼치기(읽기만 함). 결과 quest_dump.txt.

LiveQuest: ID·상태(QuestStateData) → 설명서(QuestDescriptor: 이름·주석·줄기·종류·선행 퀘스트·시작 상태)
→ 단계 나무(Tasks: 종류·ID·상태·완료 수 → ReferenceGoal: 이름·주석·위치 태그·상호작용 대상·목적지·처치 대상).
설계도는 10-22 catalog_schema.txt 기준.
"""
from __future__ import annotations

import os
import struct
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "quest_dump.txt")
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
    ue = uemem.UE(winproc.Process(), rescan=True)

    def val(a, p, depth=0):
        k = p.kind
        try:
            if k == "IntProperty":
                return str(ue.i32(a))
            if k == "FloatProperty":
                return f"{ue.f32(a):g}"
            if k in ("ByteProperty", "EnumProperty", "BoolProperty"):
                return ue.read(a, 1).hex()
            if k == "NameProperty":
                return ue.fname(a)
            if k == "StrProperty":
                return repr(ue.fstring(a))
            if k == "ObjectProperty":
                x = ue.q(a)
                return f"{ue.clsname(x)}:{ue.objname(x)[:50]}" if x else "없음"
            if k == "StructProperty":
                sn = ue.objname(p.struct)
                if sn == "GameplayTag":
                    return "#" + ue.fname(a)
                if sn == "Vector":
                    return str(tuple(round(v) for v in struct.unpack("<ddd", ue.read(a, 24))))
                if depth >= 2:
                    return sn + "{…}"
                parts = []
                for n, q in sorted(ue.props(p.struct).items(), key=lambda x: x[1].offset):
                    if "Delegate" in q.kind:
                        continue
                    parts.append(f"{n}={val(a + q.offset, q, depth + 1)}")
                return sn + "{" + ", ".join(parts)[:400] + "}"
            if k == "ArrayProperty":
                data, num, mx = struct.unpack("<Qii", ue.read(a, 16))
                if not data or not 0 <= num < 10000:
                    return "[]"
                inner = p.inner
                items = [val(data + i * inner.size, inner, depth + 1) for i in range(min(num, 8))]
                return f"[{num}개: " + ", ".join(items)[:400] + "]"
            if k == "TextProperty":
                return "(글)"
            return k
        except Exception as e:
            return f"(실패 {str(e)[:30]})"

    def fields(o, names):
        props = ue.oprops(o)
        return {n: val(o + props[n].offset, props[n]) for n in names if n in props}

    def task_tree(t, depth):
        props = ue.oprops(t)
        info = fields(t, ("ID", "State", "CompletedTaskCount"))
        log("  " * depth + f"- {ue.clsname(t)} {info}")
        if "ReferenceGoal" in props:
            g = ue.q(t + props["ReferenceGoal"].offset)
            if g:
                gi = fields(g, ("Name", "Comment", "TaskLocationTags", "InteractionTarget", "HowManyInteracts",
                                "TargetDestination", "Target", "TargetTypes", "HowMany", "NPCTag", "OtherTaskId"))
                log("  " * depth + f"    목표 {ue.clsname(g)}: {gi}")
        if "Tasks" in props and props["Tasks"].kind == "ArrayProperty" and depth < 5:
            data, num, mx = struct.unpack("<Qii", ue.read(t + props["Tasks"].offset, 16))
            for i in range(min(num, 40) if data and 0 < num < 1000 else 0):
                c = ue.q(data + i * 8)
                if c:
                    task_tree(c, depth + 1)

    quests = list(ue.find_instances("LiveQuest"))
    log(f"LiveQuest {len(quests)}개")
    for q in quests:
        try:
            props = ue.oprops(q)
            log("\n" + "=" * 70)
            log("퀘스트", fields(q, ("ID", "State", "PlayerSpecificQuestData")))
            d = ue.q(q + props["ReferenceQuest"].offset)
            if d:
                log("  설명서", fields(d, ("Name", "Comment", "QuestArcName", "ID", "IdTag", "QuestType",
                                         "InitialQuestState", "PrerequisiteQuests", "MetaData")))
            t = ue.q(q + props["Tasks"].offset)
            if t:
                task_tree(t, 1)
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
