"""게임 길찾기 데이터(내비 메시) 통째로 떠 오기(읽기만 함, 10-22 2차).

1차 결과: LovikaRecastNavMesh 액터 +0x788 = FPImplRecastNavMesh(첫 칸이 액터), 그 +8 = dtNavMesh.
dtNavMesh: +0x60 원점, +0x78/+0x80 타일 크기 3200, +0x88 최대 타일 55800, +0x8c 조회표 크기, +0xd8 posLookup,
+0xe0 nextFree, +0xe8 m_tiles. 'DNAV' 마법수는 안 보임(UE5에서 빠진 듯).
이번엔 타일 구조체 크기와 data(타일 데이터 덩어리: 머리+꼭짓점+다각형+…)·dataSize 칸을 찾아서, 쓰는 타일의 덩어리를
전부 navmesh_dump.jsonl로 보낸다(서버에서 해석). 덩어리 첫 부분 = 머리, data 포인터 = 머리 포인터.
"""
from __future__ import annotations

import base64
import json
import os
import struct
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "navmesh_probe.txt")
DUMP = os.path.join(HERE, "navmesh_dump.jsonl")
sys.path.insert(0, HERE)
CAP = 14_000_000           # 덩어리 합계 상한(압축 전)
lines: list[str] = []


def log(*a):
    s = " ".join(str(x) for x in a)
    print(s, flush=True)
    lines.append(s)


def ptr_ok(p):
    return 0x10000 < p < 0x7FFFFFFFFFFF and p % 8 == 0


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

    nav = next((o for o in ue.find_instances("LovikaRecastNavMesh") if not ue.objname(o).startswith("Default__")), None)
    if not nav:
        log("내비 메시 액터 없음")
        return
    impl = ue.q(nav + 0x788)
    if ue.q(impl) != nav:                       # 위치가 바뀌었으면 다시 찾기
        blob = rd(nav, 0x1200)
        impl = next((p for p in (struct.unpack_from("<Q", blob, k)[0] for k in range(0, 0x1200 - 8, 8))
                     if ptr_ok(p) and (rd(p, 8) or b"\0" * 8) == struct.pack("<Q", nav)), 0)
    dt = ue.q(impl + 8)
    head = rd(dt, 0x100)
    orig = struct.unpack_from("<3d", head, 0x60)
    tw, th = struct.unpack_from("<2d", head, 0x78)
    max_tiles, lut_size, lut_mask = struct.unpack_from("<3i", head, 0x88)
    pos_lookup, next_free, tiles = struct.unpack_from("<3Q", head, 0xd8)
    salt_bits, tile_bits, poly_bits = struct.unpack_from("<3i", head, 0xf0)
    log(f"dtNavMesh 0x{dt:x} 원점 {orig} 타일 {tw}x{th} 최대 {max_tiles} 조회표 {lut_size} 비트 {salt_bits}/{tile_bits}/{poly_bits}")
    log(f"m_tiles 0x{tiles:x} nextFree 0x{next_free:x} (차이 0x{next_free - tiles:x})")

    t0 = rd(tiles, 0x200)
    log("tiles[0] 앞 0x200(8바이트씩):")
    for k in range(0, 0x200, 8):
        q = struct.unpack_from("<Q", t0, k)[0]
        i1, i2 = struct.unpack_from("<ii", t0, k)
        log(f"  +0x{k:03x} {q:016x} int({i1},{i2}){' PTR' if ptr_ok(q) else ''}")
    # header 칸(+8 예상)과 같은 값을 가진 다른 칸 = data, 그 다음 int = dataSize
    hdr_off, data_off = None, None
    for ho in range(0, 0x40, 8):
        h = struct.unpack_from("<Q", t0, ho)[0]
        if not ptr_ok(h):
            continue
        for do in range(ho + 8, 0x200 - 8, 8):
            if struct.unpack_from("<Q", t0, do)[0] == h:
                hdr_off, data_off = ho, do
                break
        if hdr_off is not None:
            break
    log(f"header 칸 +0x{hdr_off:x}, data 칸 +0x{data_off:x}" if hdr_off is not None else "header=data 칸 못 찾음")
    if hdr_off is None:
        return
    size_off = data_off + 8
    # 구조체 크기: 여러 원소에서 header==data가 맞는 간격
    stride = None
    for s in range(0x40, 0x400, 8):
        ok = bad = 0
        for i in range(1, 12):
            b = rd(tiles + i * s, max(data_off, hdr_off) + 8)
            if not b:
                bad += 1
                continue
            h, d = struct.unpack_from("<Q", b, hdr_off)[0], struct.unpack_from("<Q", b, data_off)[0]
            if h and h == d:
                ok += 1
            elif h or d:
                bad += 1
        if ok >= 5 and bad == 0:
            stride = s
            break
    log(f"타일 구조체 크기 0x{stride:x}" if stride else "구조체 크기 못 찾음")
    if not stride:
        return
    n_scan = min(max_tiles, 20000)
    used, total = [], 0
    with open(DUMP, "w", encoding="utf-8") as f:
        f.write(json.dumps({"meta": {"me": me, "orig": orig, "tile": [tw, th], "stride": stride, "hdr_off": hdr_off,
                                     "data_off": data_off, "bits": [salt_bits, tile_bits, poly_bits],
                                     "tile0": base64.b64encode(rd(tiles, stride)).decode()}}) + "\n")
        for i in range(n_scan):
            b = rd(tiles + i * stride, stride)
            if not b:
                break
            h = struct.unpack_from("<Q", b, hdr_off)[0]
            if not h or not ptr_ok(h):
                continue
            size = struct.unpack_from("<i", b, size_off)[0]
            if not 0 < size < 4_000_000:
                continue
            data = rd(h, size)
            if not data:
                continue
            used.append(i)
            total += size
            if total <= CAP:
                f.write(json.dumps({"i": i, "struct": base64.b64encode(b).decode(),
                                    "data": base64.b64encode(data).decode()}) + "\n")
    log(f"쓰는 타일 {len(used)}개, 덩어리 합계 {total / 1e6:.1f}MB (보낸 것 {min(total, CAP) / 1e6:.1f}MB)")
    if used:
        h = struct.unpack_from("<Q", rd(tiles + used[0] * stride, stride), hdr_off)[0]
        hb = rd(h, 0xc0)
        log("첫 타일 머리 정수 24개:", struct.unpack_from("<24i", hb, 0))
        log("머리 double(0x30~):", [round(v, 1) for v in struct.unpack_from("<18d", hb, 0x30)])


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    try:                                     # 걷기 시험(20분)이 끝날 때까지 안 기다리고 바로 보냄
        import uploader
        for name in (OUT, DUMP):
            if os.path.exists(name):
                uploader.send_file(os.path.basename(name), title="navmesh")
        os.replace(DUMP, DUMP + ".sent") if os.path.exists(DUMP) else None
    except Exception as e:
        print("바로 보내기 실패", e)
    print("\n결과를 저장했어:", OUT)
