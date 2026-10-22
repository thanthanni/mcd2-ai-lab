"""게임 길찾기 데이터(내비 메시) 찾기(읽기만 함, 10-22). 롤처럼 '멀리 찍으면 돌아서 가기'를 우리가 직접 하려고.

몹 AI가 쓰는 LovikaRecastNavMesh(RecastNavMesh 계열) 액터 안에 반사 정보에 없는 FPImplRecastNavMesh 포인터가 있고,
그 안 두 번째 칸이 Detour의 dtNavMesh다(공개 소스 구조). dtNavMesh의 타일 배열 → 각 타일의 머리(dtMeshHeader, 첫 4바이트
'DNAV' 마법수)에서 다각형·꼭짓점 수와 범위를 읽는다. 구조 위치(오프셋)는 이 게임 빌드에서 확인이 안 됐으니
마법수·내 위치 근처 좌표로 찾아서 navmesh_probe.txt에 적는다.
"""
from __future__ import annotations

import os
import struct
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "navmesh_probe.txt")
sys.path.insert(0, HERE)
MAGIC = 0x444E4156          # 'DNAV'
lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


def main():
    from state_probe import find_ohs_app
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
    me = r.loc(r.player) if r.player else None
    log("내 위치", tuple(round(v) for v in me) if me else None)

    def rd(a, n):
        try:
            return ue.read(a, n)
        except Exception:
            return None

    def ptr_ok(p):
        return 0x10000 < p < 0x7FFFFFFFFFFF and p % 8 == 0

    navs = []
    for cname in ("LovikaRecastNavMesh", "RecastNavMesh"):
        for o in ue.find_instances(cname):
            if not ue.objname(o).startswith("Default__"):
                navs.append(o)
    log("내비 메시 액터", len(navs), [ue.objname(o) for o in navs])
    for nav in navs[:2]:
        props = ue.oprops(nav)
        last = max((p.offset for p in props.values()), default=0)
        log(f"\n[{ue.objname(nav)}] 반사 속성 {len(props)}개, 마지막 오프셋 0x{last:x}")
        for name in ("AgentRadius", "AgentHeight", "TileSizeUU", "CellSize", "AgentMaxStepHeight", "bIsWorldPartitioned"):
            if name in props:
                raw = rd(nav + props[name].offset, 8)
                log(f"  {name} @0x{props[name].offset:x} {props[name].kind} {raw.hex() if raw else '?'}")
        blob = rd(nav, 0x1200) or b""
        # FPImplRecastNavMesh: 첫 칸이 이 액터를 가리킴
        impls = []
        for off in range(0, len(blob) - 8, 8):
            p = struct.unpack_from("<Q", blob, off)[0]
            if ptr_ok(p):
                b = rd(p, 16)
                if b and struct.unpack_from("<Q", b)[0] == nav:
                    impls.append((off, p, struct.unpack_from("<Q", b, 8)[0]))
        log("  impl 후보(오프셋, 주소, 두 번째 칸)", [(hex(a), hex(b), hex(c)) for a, b, c in impls])
        for off, impl, dt in impls[:2]:
            if not ptr_ok(dt):
                continue
            d = rd(dt, 0x180)
            if not d:
                continue
            log(f"\n  dtNavMesh 0x{dt:x} 앞부분(8바이트씩: 정수 두 개 / 실수 / 포인터 여부)")
            for k in range(0, 0x180, 8):
                q = struct.unpack_from("<Q", d, k)[0]
                i1, i2 = struct.unpack_from("<ii", d, k)
                f = struct.unpack_from("<d", d, k)[0]
                log(f"    +0x{k:03x} {q:016x} int({i1},{i2}) dbl({f:.6g}){' PTR' if ptr_ok(q) else ''}")
            # 타일 배열 찾기: 포인터 칸 → 그 배열 원소 안 어딘가에 'DNAV' 머리를 가리키는 포인터
            for k in range(0, 0x180, 8):
                arr = struct.unpack_from("<Q", d, k)[0]
                if not ptr_ok(arr):
                    continue
                first = rd(arr, 0x100)
                if not first:
                    continue
                for ho in range(0, 0x100 - 8, 8):
                    hp = struct.unpack_from("<Q", first, ho)[0]
                    if not ptr_ok(hp):
                        continue
                    h = rd(hp, 4)
                    if h and struct.unpack_from("<I", h)[0] == MAGIC:
                        log(f"\n  ★ 타일 배열 = dtNavMesh+0x{k:x} → 0x{arr:x}, 원소 안 header 오프셋 +0x{ho:x}")
                        scan_tiles(ue, rd, ptr_ok, arr, ho, me, log)
                        return
    log("타일 배열을 못 찾았어(구조가 다름). 위 덤프로 다시 봐야 함.")


def scan_tiles(ue, rd, ptr_ok, arr, ho, me, log):
    # 원소 크기 찾기: 다음 원소의 header도 DNAV이거나 0인 간격
    first = rd(arr, 0x400)
    sizes = []
    for sz in range(0x40, 0x200, 8):
        ok = 0
        for i in range(1, 6):
            b = rd(arr + i * sz + ho, 8)
            if not b:
                break
            hp = struct.unpack_from("<Q", b)[0]
            if hp == 0:
                continue
            h = rd(hp, 4) if ptr_ok(hp) else None
            if h and struct.unpack_from("<I", h)[0] == MAGIC:
                ok += 1
            else:
                ok = -99
        if ok > 0:
            sizes.append((ok, sz))
    log("  원소 크기 후보(맞은 수, 크기)", sizes[:6])
    log("  첫 원소(8바이트씩):", " ".join(f"{struct.unpack_from('<Q', first, k)[0]:x}" for k in range(0, 0xa0, 8)))
    hp = struct.unpack_from("<Q", first, ho)[0]
    hb = rd(hp, 0x100)
    ints = struct.unpack_from("<16i", hb, 0)
    log("  첫 타일 header 정수 16개(magic,version,x,y,layer,userId,polyCount,vertCount,maxLink,detailMesh,detailVert,"
        "detailTri,bvNode,offMeshCon,offMeshBase,…):", ints)
    log("  header 뒤 실수(double)", [round(v, 2) for v in struct.unpack_from("<16d", hb, 0x40)])
    log("  header 뒤 실수(float)", [round(v, 2) for v in struct.unpack_from("<24f", hb, 0x40)])
    log("  첫 원소 포인터들 앞 64바이트 실수(double) — 꼭짓점 배열 후보:")
    for k in range(0, 0xa0, 8):
        p = struct.unpack_from("<Q", first, k)[0]
        if ptr_ok(p) and p != hp:
            b = rd(p, 48)
            if b:
                log(f"    +0x{k:x}: dbl {[round(v, 1) for v in struct.unpack_from('<6d', b)]} flt {[round(v, 1) for v in struct.unpack_from('<6f', b)]}")
    if not sizes:
        return
    sz = sizes[0][1]
    n, polys, verts = 0, 0, 0
    for i in range(4096):
        b = rd(arr + i * sz + ho, 8)
        if not b:
            break
        p = struct.unpack_from("<Q", b)[0]
        if not p:
            continue
        h = rd(p, 0x40) if ptr_ok(p) else None
        if not h or struct.unpack_from("<I", h)[0] != MAGIC:
            continue
        v = struct.unpack_from("<16i", h)
        n += 1
        polys += v[6]
        verts += v[7]
    log(f"  타일(원소 크기 0x{sz:x}로 4096칸 훑음): 쓰는 타일 {n}개, 다각형 {polys}, 꼭짓점 {verts}")
    if me:
        log(f"  비교용 내 위치(언리얼) {tuple(round(v) for v in me)} → Recast 좌표는 보통 (-x, z, -y)")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
