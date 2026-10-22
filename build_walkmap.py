"""걸어 본 길 지도 만들기(서버에서 실행). 봇 기록(trace_*.jsonl)·장훈 플레이 기록(play_*.jsonl)의 위치를
200칸(높이 400마다 다른 층)으로 나누고, 0.1~1.2초 사이에 이어서 지나간 두 칸을 '걸어서 이어짐'으로 잇는다.
순간이동(1.2초에 600 넘게)·낙하(높이 250 넘게)는 잇지 않는다. 결과 state/walkmap.json → nav.py가 길을 찾을 때 씀.
사용: python3 build_walkmap.py <기록 폴더> [출력]"""
import glob
import json
import math
import os
import sys

CELL, LAYER = 200, 400


def key(p):
    return (int(p[0] // CELL), int(p[1] // CELL), int(p[2] // LAYER))


def rows(path):
    for line in open(path, encoding="utf-8"):
        try:
            r = json.loads(line)
        except ValueError:
            continue
        p = r.get("p") or (r.get("me") or {}).get("p")
        if p and r.get("t") is not None:
            yield r["t"], p


def main():
    src = sys.argv[1]
    out = sys.argv[2] if len(sys.argv) > 2 else os.path.join(os.path.dirname(__file__), "..", "state", "walkmap.json")
    cells, edges = {}, set()
    files = sorted(glob.glob(os.path.join(src, "trace_*.jsonl")) + glob.glob(os.path.join(src, "play_*.jsonl")))
    for f in files:
        prev = None
        for t, p in rows(f):
            k = key(p)
            c = cells.setdefault(k, [0.0, 0.0, 0.0, 0])
            c[0] += p[0]; c[1] += p[1]; c[2] += p[2]; c[3] += 1
            if prev:
                dt = t - prev[0]
                d = math.hypot(p[0] - prev[1][0], p[1] - prev[1][1])
                if 0 < dt <= 1.2 and d <= 600 and abs(p[2] - prev[1][2]) <= 250:
                    a, b = key(prev[1]), k
                    if a != b:
                        edges.add((a, b) if a < b else (b, a))
            prev = (t, p)
    # 칸 대표 위치 = 실제로 서 있던 자리 평균(칸 가운데가 벽 속일 수 있어서)
    data = {"cell": CELL, "layer": LAYER,
            "cells": {f"{k[0]},{k[1]},{k[2]}": [round(c[0] / c[3]), round(c[1] / c[3]), round(c[2] / c[3]), c[3]]
                      for k, c in cells.items()},
            "edges": [[f"{a[0]},{a[1]},{a[2]}", f"{b[0]},{b[1]},{b[2]}"] for a, b in sorted(edges)]}
    json.dump(data, open(out, "w"), separators=(",", ":"))
    xs = [c[0] for c in data["cells"].values()]
    ys = [c[1] for c in data["cells"].values()]
    print(f"기록 {len(files)}개 → 칸 {len(cells)}, 이음 {len(edges)}, x {min(xs)}~{max(xs)}, y {min(ys)}~{max(ys)} → {out}")


if __name__ == "__main__":
    main()
