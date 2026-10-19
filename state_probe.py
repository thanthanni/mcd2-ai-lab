"""마던2 게임 상태 탐색기(읽기만 함).

Offline Hero Sync의 읽기 전용 메모리 해석기(uemem.py, winproc.py)를 빌려서
게임 안에 어떤 캐릭터·몹·체력 정보가 있는지 훑고 state_probe.txt로 남긴다.
게임은 읽기만 하고(OpenProcess: QUERY_INFORMATION | VM_READ) 절대 바꾸지 않는다.
오프라인 캐릭터로 월드에 들어가 몹이 근처에 있을 때 실행한다.
"""
from __future__ import annotations

import glob
import os
import struct
import sys
import time
import traceback

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state_probe.txt")
lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


def find_ohs_app() -> str | None:
    home = os.path.expanduser("~")
    roots = [os.path.join(os.environ.get("LOCALAPPDATA", ""), "MCD2Helper", "OfflineHeroSync")]
    for d in ("Documents", "문서", "Downloads", "Desktop", "바탕 화면", os.path.join("OneDrive", "Documents"), os.path.join("OneDrive", "문서")):
        roots.append(os.path.join(home, d))
    for r in roots:
        for pat in ("app", "*/app", "*/*/app", "*/*/*/app"):
            for p in glob.glob(os.path.join(r, pat)):
                if os.path.isfile(os.path.join(p, "uemem.py")) and os.path.isfile(os.path.join(p, "winproc.py")):
                    return p
    return None


def vec(ue, addr):
    """UE5 FVector = double 3개"""
    return struct.unpack("<ddd", ue.read(addr, 24))


def main():
    app = find_ohs_app()
    if not app:
        log("Offline Hero Sync 폴더(app\\uemem.py)를 못 찾았어. 문서나 다운로드 아래에 압축을 풀어 둔 곳을 알려 줘.")
        return
    sys.path.insert(0, app)
    import winproc  # noqa
    import uemem    # noqa
    log("해석기 위치:", app)
    proc = winproc.Process()
    log("게임 프로세스:", proc.pid, proc.exe)
    t = time.time()
    ue = uemem.UE(proc, rescan=True)
    log(f"엔진 표 찾음 ({time.time() - t:.1f}초), 빌드 {ue.exe_key()}, 객체 {ue.num_objs()}개")

    # 1. 클래스별 개수 + 상위 클래스 사슬(캐시)
    t = time.time()
    cls_name, cls_chain, count, members = {}, {}, {}, {}
    for o in ue.iter_objects():
        try:
            c = ue.cls(o)
            if c not in cls_name:
                cls_name[c] = ue.objname(c)
                chain = []
                x = c
                for _ in range(40):
                    if not x:
                        break
                    chain.append(ue.objname(x))
                    x = ue.q(x + uemem.S_SUPER)
                cls_chain[c] = chain
            n = cls_name[c]
            count[n] = count.get(n, 0) + 1
            if "Pawn" in cls_chain[c] and not ue.objname(o).startswith("Default__"):
                members.setdefault(n, []).append(o)
        except Exception:
            continue
    log(f"훑기 {time.time() - t:.1f}초, 클래스 {len(cls_name)}종")

    log("\n[캐릭터·몹(Pawn 계열) 종류별 개수]")
    for n, objs in sorted(members.items(), key=lambda x: -len(x[1]))[:60]:
        c = ue.cls(objs[0])
        log(f"  {n}: {len(objs)}개   상위: {' > '.join(cls_chain[c][1:6])}")

    log("\n[이름에 체력·속성·플레이어가 들어간 클래스]")
    keys = ("Attribute", "ATR_", "Health", "Player", "Hero", "Mob", "Enemy", "Soul", "Cooldown")
    for n, k in sorted(count.items(), key=lambda x: -x[1]):
        if any(s.lower() in n.lower() for s in keys):
            log(f"  {n}: {k}개")

    # 2. 플레이어 컨트롤러 → 내 캐릭터
    pawn = None
    for pc_cls in ("PlayerController",):
        try:
            for pc in ue.find_instances(pc_cls):
                for fld in ("AcknowledgedPawn", "Pawn"):
                    try:
                        p = ue.q(pc + ue.field(pc, fld).offset)
                        if p:
                            pawn = p
                            break
                    except KeyError:
                        continue
                if pawn:
                    break
        except Exception:
            log("컨트롤러 찾기 실패:", traceback.format_exc(limit=1))
    if not pawn:
        log("\n내 캐릭터를 못 찾았어. 월드에 들어간 상태인지 확인해 줘.")
    else:
        log(f"\n[내 캐릭터] {ue.fullname(pawn)}")
        props = ue.oprops(pawn)
        log(f"  속성 {len(props)}개:")
        for name, p in sorted(props.items(), key=lambda x: x[1].offset):
            log(f"    +{p.offset:#06x} {p.kind:22s} {name}")
        try:
            root = ue.q(pawn + ue.field(pawn, "RootComponent").offset)
            loc_off = ue.field(root, "RelativeLocation").offset
            me = vec(ue, root + loc_off)
            log(f"  위치: {tuple(round(v, 1) for v in me)}")
            # 3. 주변 캐릭터·몹 위치
            log("\n[주변 캐릭터·몹 위치(내 위치 기준 거리)]")
            near = []
            for n, objs in members.items():
                for o in objs[:200]:
                    try:
                        r = ue.q(o + ue.field(o, "RootComponent").offset)
                        if not r:
                            continue
                        v = vec(ue, r + loc_off)
                        d = sum((a - b) ** 2 for a, b in zip(v, me)) ** 0.5
                        near.append((d, n, v))
                    except Exception:
                        continue
            for d, n, v in sorted(near)[:40]:
                log(f"  {d:8.0f}  {n}  {tuple(round(x) for x in v)}")
            # 4. 읽기 속도
            t = time.time()
            for _ in range(200):
                vec(ue, root + loc_off)
            log(f"\n[속도] 내 위치 200번 읽기 {1000 * (time.time() - t):.0f}ms")
        except Exception:
            log("위치 읽기 실패:", traceback.format_exc(limit=2))

    # 5. 속성(체력 등) 객체 내용
    log("\n[속성 묶음(AttributeSet) 값]")
    shown = 0
    for n, k in sorted(count.items(), key=lambda x: -x[1]):
        if not (("Attribute" in n and "Set" in n) or n.startswith("ATR_")):
            continue
        try:
            for o in ue.find_instances(n)[:3]:
                outer = ue.objname(ue.outer(o)) if ue.outer(o) else "?"
                log(f"  {n} (주인: {outer})")
                for name, p in sorted(ue.oprops(o).items(), key=lambda x: x[1].offset):
                    if p.kind == "StructProperty":
                        base, cur = struct.unpack("<ff", ue.read(o + p.offset + 8, 8))
                        log(f"    {name}: 기본 {base:.1f} / 현재 {cur:.1f}")
                    elif p.kind in ("FloatProperty", "IntProperty"):
                        v = ue.f32(o + p.offset) if p.kind == "FloatProperty" else ue.i32(o + p.offset)
                        log(f"    {name}: {v}")
                shown += 1
        except Exception:
            log("  읽기 실패:", n)
        if shown >= 12:
            break


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
