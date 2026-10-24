"""게임 길찾기 지도(Detour 내비 메시)를 메모리에서 읽어 롤처럼 '돌아서 가는' 경로를 만든다(10-22).

구조(navmesh_probe 1·2차로 확인, UE 5.6 마던2):
  LovikaRecastNavMesh 액터 +0x788 → FPImplRecastNavMesh(첫 칸=액터) → +8 dtNavMesh
  dtNavMesh +0xe8 m_tiles(원소 0xa8), +0x88 m_maxTiles. 타일 +0x8 header, +0x50 data, +0x58 dataSize
  data(머리 0x58): int version(7), u16 polyCount, u16 vertCount, int x, int y, … double bmin[3] @0x28, bmax[3] @0x40
    → 꼭짓점 double[3] × vertCount @0x58 → 다각형 32바이트 × polyCount
       (u32 firstLink, u16 verts[6], u16 neis[6], u16 flags, u8 vertCount, u8 area|type<<6)
  Recast 좌표 (rx, ry=높이, rz) = 언리얼 (-X, Z, -Y).
월드가 구역별로 불러와서 내 주변 타일만 메모리에 있다(10-22: 106개, 마을~북쪽 필드).

경로: 다각형 그래프 A*(공유 모서리 = 통로) → 깔때기(string pulling)로 꺾이는 점만 → 언리얼 좌표.
타일 경계 통로는 모서리가 딱 안 겹칠 수 있어 경계선 위 모서리끼리 겹치는 구간으로 잇는다.
"""
from __future__ import annotations

import heapq
import math
import struct

ACTOR_IMPL = 0x788
TILE_STRIDE, T_HDR, T_DATA, T_SIZE = 0xa8, 0x8, 0x50, 0x58
DT_TILES, DT_MAXTILES = 0xe8, 0x88
HDR = 0x58
TILE = 3200.0


def jkey(a, b):
    """단차 점 쌍의 이름(지도를 다시 읽어도 같은 값)."""
    return tuple(round(v) for v in a[:3]) + tuple(round(v) for v in b[:3])


def ptr_ok(p):
    return 0x10000 < p < 0x7FFFFFFFFFFF


def read_tiles(ue, nav_actor, limit=20000, runtime=None):
    """메모리 → [data bytes, ...] (쓰는 타일만)."""
    impl = ue.q(nav_actor + ACTOR_IMPL)
    if ue.q(impl) != nav_actor:
        raise RuntimeError("FPImplRecastNavMesh 위치가 다름")
    dt = ue.q(impl + 8)
    tiles = ue.q(dt + DT_TILES)
    maxt = min(ue.i32(dt + DT_MAXTILES), limit)
    out = []
    raw = ue.read(tiles, maxt * TILE_STRIDE)
    for i in range(maxt):
        h = struct.unpack_from("<Q", raw, i * TILE_STRIDE + T_HDR)[0]
        if not h or not ptr_ok(h):
            continue
        size = struct.unpack_from("<i", raw, i * TILE_STRIDE + T_SIZE)[0]
        if 0 < size < 4_000_000:
            try:
                data = ue.read(h, size)
                out.append(data)
                if runtime is not None:
                    tr = raw[i*TILE_STRIDE:(i+1)*TILE_STRIDE]
                    count, capacity = struct.unpack_from('<II', tr, 0x98)
                    lp, dp = struct.unpack_from('<Q', tr, 0x20)[0], struct.unpack_from('<Q', tr, 0x90)[0]
                    ml = struct.unpack_from('<H', data, 16)[0]
                    rec = {'index':i, 'salt':struct.unpack_from('<I',tr)[0], 'maxlinks':ml, 'links':b'', 'dynamic':b''}
                    runtime.append(rec)
                    if ml < 16384:
                        rec['links'] = ue.read(lp, ml*16)
                    if 0 < count <= capacity < 16384 and ptr_ok(dp):
                        rec['dynamic'] = ue.read(dp, count*16)
            except Exception:
                pass
    return out


def read_navmesh(ue, actor):
    dt = ue.q(ue.q(actor + ACTOR_IMPL) + 8)
    if struct.unpack('<3i', ue.read(dt + 0xf0, 12)) != (17, 16, 31):
        raise RuntimeError("내비 메시 참조 비트가 바뀜")
    runtime = []
    blobs = read_tiles(ue, actor, runtime=runtime)
    mesh = NavMesh(blobs)
    mesh.add_runtime_links(runtime)
    return mesh


class NavMesh:
    def __init__(self, blobs):
        self.verts = []      # 다각형별 [(X, Y, Z) 언리얼]
        self.center = []
        self.adj = []        # 다각형별 [(이웃, 통로 a, 통로 b)]  통로는 언리얼 (X, Y, Z)
        self.grid = {}       # (gx, gy) 1000칸 → 다각형 번호들
        self.tile_ground, self.tile_off, self.tile_first = [], [], []
        self.jump_edges, self.jump_pairs = {}, {}
        self.banned = set()   # 실제로 못 건넌 단차(a, b) 점 쌍: 길 찾기에서 뺌(nav가 채움, 몹 전용 연결 등)
        edges, border = {}, {}
        for d in blobs:
            ground, off, first = {}, {}, {}
            self.tile_ground.append(ground)
            self.tile_off.append(off)
            self.tile_first.append(first)
            ver, npoly, nvert, tx, ty = struct.unpack_from("<iHHii", d, 0)
            if ver != 7 or HDR + nvert * 24 + npoly * 32 > len(d):
                continue
            vs = [struct.unpack_from("<3d", d, HDR + k * 24) for k in range(nvert)]
            vs = [(-v[0], -v[2], v[1]) for v in vs]                  # → 언리얼
            po = HDR + nvert * 24
            for k in range(npoly):
                f = struct.unpack_from("<I6H6HHBB", d, po + k * 32)
                n, area = f[14], f[15] & 0x3f
                first[k] = f[0]
                if (f[15] >> 6) == 1 and n == 2 and area:
                    off[k] = tuple(vs[i] for i in f[1:3])
                if n < 3 or (f[15] >> 6) == 1 or area == 0:     # 1 = 오프메시 연결(점프 링크), 0 = 못 걷는 곳
                    continue
                pv = [vs[i] for i in f[1:1 + n]]
                pid = len(self.verts)
                ground[k] = pid
                self.verts.append(pv)
                cx = sum(p[0] for p in pv) / n
                cy = sum(p[1] for p in pv) / n
                cz = sum(p[2] for p in pv) / n
                self.center.append((cx, cy, cz))
                self.adj.append([])
                xs, ys = [p[0] for p in pv], [p[1] for p in pv]
                for gx in range(int(min(xs) // 1000), int(max(xs) // 1000) + 1):
                    for gy in range(int(min(ys) // 1000), int(max(ys) // 1000) + 1):
                        self.grid.setdefault((gx, gy), []).append(pid)
                for j in range(n):
                    a, b = pv[j], pv[(j + 1) % n]
                    ka = (round(a[0]), round(a[1]), round(a[2] / 50))
                    kb = (round(b[0]), round(b[1]), round(b[2] / 50))
                    edges.setdefault((ka, kb) if ka < kb else (kb, ka), []).append((pid, a, b))
                    # 타일 경계 위 모서리(두 점이 같은 경계선 위)
                    for axis in (0, 1):
                        if abs(a[axis] - b[axis]) < 1 and abs(a[axis] / TILE - round(a[axis] / TILE)) < 1e-3:
                            border.setdefault((axis, round(a[axis])), []).append((pid, a, b))
        for lst in edges.values():
            if len(lst) == 2:
                (p, a, b), (q, _, _) = lst
                if p != q:
                    self._link(p, q, a, b)
        for (axis, _), lst in border.items():          # 경계선 위에서 다른 다각형 모서리와 겹치는 구간
            o = 1 - axis
            for i in range(len(lst)):
                p, a, b = lst[i]
                lo1, hi1 = sorted((a[o], b[o]))
                for j in range(i + 1, len(lst)):
                    q, c, e = lst[j]
                    if q == p or any(n == q for n, _, _ in self.adj[p]):
                        continue
                    lo2, hi2 = sorted((c[o], e[o]))
                    lo, hi = max(lo1, lo2), min(hi1, hi2)
                    if hi - lo < 30 or abs((a[2] + b[2]) / 2 - (c[2] + e[2]) / 2) > 120:
                        continue
                    pa, pb = list(a), list(a)
                    pa[o], pb[o] = lo, hi
                    pa[2] = pb[2] = (a[2] + b[2] + c[2] + e[2]) / 4
                    self._link(p, q, tuple(pa), tuple(pb))

    def add_runtime_links(self, runtime):
        """엔진이 실제 연결한 방향만 사용한다. 단차의 역방향 연결을 임의로 만들지 않는다."""
        refs, links, off = {}, {}, {}
        for ti, rec in enumerate(runtime):
            if ti >= len(self.tile_ground):
                break
            base = (rec['salt'] << 47) | (rec['index'] << 31)
            for poly, pid in self.tile_ground[ti].items():
                refs[base | poly] = pid
            for poly, points in self.tile_off[ti].items():
                off[base | poly] = points
            for poly, first in self.tile_first[ti].items():
                out, seen, idx = [], set(), first
                while idx != 0xffffffff and idx not in seen and len(seen) < 256:
                    seen.add(idx)
                    raw, j = ((rec['links'], idx) if idx < rec['maxlinks'] else
                              (rec['dynamic'], idx - rec['maxlinks']))
                    if j * 16 + 16 > len(raw):
                        break
                    ref, idx, edge, _, _, _ = struct.unpack_from('<QIBBBB', raw, j * 16)
                    if ref:
                        out.append((ref, edge))
                links[base | poly] = out
        for ref, pid in refs.items():
            for conn, _ in links.get(ref, ()):
                if conn not in off:
                    continue
                exits = links.get(conn, ())
                entry = next((edge for back, edge in exits if back == ref and edge in (0, 1)), None)
                if entry is None:
                    continue
                a, b = off[conn][entry], off[conn][1-entry]
                for dest, edge in exits:
                    q = refs.get(dest)
                    if q is None or q == pid or edge != 1-entry:
                        continue
                    if any(n == q for n, _, _ in self.adj[pid]):
                        continue
                    self.adj[pid].append((q, a, b))
                    self.jump_edges[(pid, q)] = (a, b)
                    self.jump_pairs[(a, b)] = True

    def _link(self, p, q, a, b):
        self.adj[p].append((q, a, b))
        self.adj[q].append((p, a, b))

    def __len__(self):
        return len(self.verts)

    @staticmethod
    def _inside(pv, x, y):
        inside = False
        n = len(pv)
        for i in range(n):
            ax, ay = pv[i][0], pv[i][1]
            bx, by = pv[(i + 1) % n][0], pv[(i + 1) % n][1]
            if (ay > y) != (by > y) and x < (bx - ax) * (y - ay) / (by - ay) + ax:
                inside = not inside
        return inside

    def find(self, p, maxd=400):
        """점이 들어 있는 다각형(높이 차 가장 작은 것). 없으면 maxd 안 가장 가까운 중심."""
        x, y, z = p
        best, bd = None, 1e18
        cands = self.grid.get((int(x // 1000), int(y // 1000)), [])
        for k in cands:
            if self._inside(self.verts[k], x, y):
                dz = abs(self.center[k][2] - z)
                if dz < 300 and dz < bd:
                    best, bd = k, dz
        if best is not None:
            return best
        for gx in range(int(x // 1000) - 1, int(x // 1000) + 2):
            for gy in range(int(y // 1000) - 1, int(y // 1000) + 2):
                for k in self.grid.get((gx, gy), []):
                    c = self.center[k]
                    d = math.hypot(c[0] - x, c[1] - y) + abs(c[2] - z)
                    if d < bd and d < maxd:
                        best, bd = k, d
        return best

    def path(self, start, goal):
        """언리얼 점 → 언리얼 점. 꺾이는 점 목록(시작 제외, 목표 포함) 또는 None."""
        s, t = self.find(start), self.find(goal)
        self.why = "start" if s is None else "goal" if t is None else ""   # 실패 이유(시작/목표가 지도 밖, 아니면 끊김)
        if s is None or t is None:
            return None
        if s == t:
            return [tuple(goal)]
        g, prev = self._search(s, self.center[t], t)
        if t not in g:
            self.why = "split"
            return None
        return self._build(s, t, prev, start, goal)

    def path_toward(self, start, goal, min_gain=500):
        """목표까지 이어진 길이 없을 때(목표 쪽 지도가 아직 안 불러와졌거나 끊김): 내가 닿을 수 있는 다각형 중
        목표에 가장 가까운 곳까지의 경로. 지금보다 min_gain 이상 가까워지지 않으면 None. (경로, 그 끝점)"""
        s = self.find(start)
        if s is None:
            return None, None
        g, prev = self._search(s, None, None)
        best = min(g, key=lambda k: math.hypot(self.center[k][0] - goal[0], self.center[k][1] - goal[1]))
        end = self.center[best]
        if math.hypot(end[0] - goal[0], end[1] - goal[1]) > math.hypot(start[0] - goal[0], start[1] - goal[1]) - min_gain:
            return None, None
        return self._build(s, best, prev, start, end), end

    def _search(self, s, tc, t):
        """A*(tc가 있으면) 또는 닿는 곳 전부 Dijkstra. (거리, 직전 정보)"""
        g = {s: 0.0}
        prev = {}
        pq = [(0.0, s)]
        done = set()
        while pq:
            _, u = heapq.heappop(pq)
            if u == t:
                break
            if u in done:
                continue
            done.add(u)
            cu = self.center[u]
            for v, a, b in self.adj[u]:
                if (u, v) in self.jump_edges and jkey(a, b) in self.banned:
                    continue
                m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                if (u, v) in self.jump_edges:
                    w = math.dist(cu, a) + math.dist(a, b) + math.dist(b, self.center[v]) + 100
                else:
                    w = math.hypot(m[0] - cu[0], m[1] - cu[1]) + math.hypot(self.center[v][0] - m[0], self.center[v][1] - m[1])
                nd = g[u] + w
                if nd < g.get(v, 1e18):
                    g[v], prev[v] = nd, (u, a, b)
                    c = self.center[v]
                    heapq.heappush(pq, (nd + (math.hypot(c[0] - tc[0], c[1] - tc[1]) if tc else 0.0), v))
        return g, prev

    def _build(self, s, t, prev, start, goal):
        portals = []
        k = t
        while k != s:
            u, a, b = prev[k]
            portals.append((u, k, a, b))
            k = u
        portals.reverse()
        points, walk, anchor = [], [], start
        for u, v, a, b in portals:
            if (u, v) in self.jump_edges:
                points.extend(self._funnel(anchor, a, walk))
                points.append(b)
                anchor, walk = b, []
            else:
                walk.append((u, a, b))
        points.extend(self._funnel(anchor, goal, walk))
        return points

    def _funnel(self, start, goal, portals):
        """깔때기(simple stupid funnel): 통로마다 진행 방향 기준 (왼쪽, 오른쪽)을 정해서 꺾이는 점만 남긴다."""
        def cross(o, a, b):
            return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

        pts = [(tuple(start), tuple(start))]
        for k, (u, a, b) in enumerate(portals):
            c0 = self.center[u]
            c1 = portals[k + 1][1] if k + 1 < len(portals) else goal
            m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
            d = (m[0] - c0[0], m[1] - c0[1])
            if d[0] * (a[1] - m[1]) - d[1] * (a[0] - m[0]) > 0:   # a가 진행 방향 왼쪽
                pts.append((a, b))
            else:
                pts.append((b, a))
        pts.append((tuple(goal), tuple(goal)))
        out = []
        apex = left = right = pts[0][0]
        ai = li = ri = 0
        i = 1
        steps, cap = 0, 8 * len(pts) + 50
        while i < len(pts):
            steps += 1
            if steps > cap:   # 겹친 점·퇴화한 통로에서 같은 자리를 끝없이 도는 경우(10-23/24 따라가기 판이 멈춤) → 통로 가운데 점으로
                return [((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, (a[2] + b[2]) / 2) for _, a, b in portals] + [tuple(goal)]
            nl, nr = pts[i]
            if cross(apex, right, nr) >= 0:                        # 오른쪽 변을 안쪽으로 좁힘
                if apex == right or cross(apex, left, nr) < 0:
                    right, ri = nr, i
                else:                                              # 왼쪽 변을 넘음 → 왼쪽 점이 꺾이는 점
                    out.append(left)
                    apex, ai = left, li
                    left = right = apex
                    li = ri = ai
                    i = ai + 1
                    continue
            if cross(apex, left, nl) <= 0:                         # 왼쪽 변을 안쪽으로 좁힘
                if apex == left or cross(apex, right, nl) > 0:
                    left, li = nl, i
                else:
                    out.append(right)
                    apex, ai = right, ri
                    left = right = apex
                    li = ri = ai
                    i = ai + 1
                    continue
            i += 1
        out.append(tuple(goal))
        clean = []
        for p in out:
            if not clean or math.dist(clean[-1][:2], p[:2]) > 20:
                clean.append(p)
        return clean
