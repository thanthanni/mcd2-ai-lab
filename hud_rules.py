"""화면 규칙으로 입력 알아내기(영상에 정답 붙일 때 IDM을 돕는다).

- 유물·물약: 쓰는 순간 그 칸이 회색으로 덮여 색이 확 빠진다(채도 0.31 → 0.14, 1920x1080 캡처 3장으로 확인, 10-18).
- 이동: 카메라가 캐릭터를 따라가서, 배경이 흘러가는 방향의 반대가 왼쪽 스틱 방향이다.
기본 패드 배치(엑스박스): 물약 LT, 유물1 Y, 유물2 B, 유물3 RB (https://www.dungeons.tools/2/controls)

    python hud_rules.py --eval <녹화 data 폴더>     # 내 녹화로 규칙이 얼마나 맞는지 채점
"""
from __future__ import annotations

import argparse
import math

import numpy as np

# 칸 위치(1920x1080 기준 비율). 게임 화면이 잘려 들어와도 비율이라 그대로 쓴다.
SLOTS = {
    "potion": (560, 985, 605, 1030),
    "a1": (820, 915, 905, 1000),
    "a2": (922, 915, 1007, 1000),
    "a3": (1023, 915, 1108, 1000),
}
SLOT_PAD = {"potion": "lt", "a1": "y", "a2": "b", "a3": "rb"}


def slot_saturation(frames: np.ndarray) -> dict[str, np.ndarray]:
    """frames [N,H,W,3] uint8 → 칸별 평균 채도 [N]"""
    n, h, w, _ = frames.shape
    out = {}
    for k, (x1, y1, x2, y2) in SLOTS.items():
        ys, ye = int(y1 / 1080 * h), max(int(y1 / 1080 * h) + 1, int(math.ceil(y2 / 1080 * h)))
        xs, xe = int(x1 / 1920 * w), max(int(x1 / 1920 * w) + 1, int(math.ceil(x2 / 1920 * w)))
        c = frames[:, ys:ye, xs:xe].astype(np.float32)
        mx, mn = c.max(3), c.min(3)
        out[k] = ((mx - mn) / (mx + 1)).mean((1, 2))
    return out


def detect_presses(sat: np.ndarray, others: np.ndarray | None = None, drop: float = 0.09,
                   hold: int = 10, refractory: int = 20) -> np.ndarray:
    """채도가 직전 1초 평균보다 drop 넘게 떨어지고, 그 뒤 1초(hold장) 중 대부분 낮게 유지되면 누른 순간.
    others(다른 칸들의 채도 평균)도 같이 떨어지면 장면이 어두워진 것(불꽃·메뉴 등)이라 무시한다."""
    n = len(sat)
    press = np.zeros(n, bool)
    last = -10**9
    for t in range(10, n - hold - 1):
        if t - last <= refractory:
            continue
        base = np.median(sat[t - 10:t])
        if not (base - sat[t] < drop and base - sat[t + 1] > drop):
            continue
        if (base - sat[t + 1:t + 1 + hold] > drop * 0.7).mean() < 0.8:
            continue
        if others is not None:
            ob = np.median(others[t - 10:t])
            if ob - others[t + 1:t + 1 + hold].mean() > drop * 0.6:
                continue
        press[t] = True
        last = t
    return press


def slot_presses(frames: np.ndarray) -> dict[str, np.ndarray]:
    sat = slot_saturation(frames)
    out = {}
    for k in SLOTS:
        others = np.mean([sat[o] for o in SLOTS if o != k], 0)
        out[k] = detect_presses(sat[k], others)
    return out


def motion_classes(frames: np.ndarray, min_shift: float = 0.6) -> np.ndarray:
    """t→t+1 사이 배경 이동(위상 상관)으로 왼쪽 스틱 방향(0=가만, 1..8). 아래 HUD와 오른쪽 위 지도는 뺀다."""
    n, h, w, _ = frames.shape
    g = frames.astype(np.float32).mean(3)
    g = g[:, : int(h * 0.78), : int(w * 0.84)]
    win = np.outer(np.hanning(g.shape[1]), np.hanning(g.shape[2]))
    F = np.fft.rfft2((g - g.mean((1, 2), keepdims=True)) * win)
    out = np.zeros(n, np.int64)
    for t in range(n - 1):
        R = F[t + 1] * np.conj(F[t])
        R /= np.abs(R) + 1e-6
        r = np.fft.irfft2(R, s=g.shape[1:])
        dy, dx = np.unravel_index(np.argmax(r), r.shape)
        if dy > g.shape[1] // 2: dy -= g.shape[1]
        if dx > g.shape[2] // 2: dx -= g.shape[2]
        # 캐릭터가 오른쪽으로 가면 배경은 왼쪽으로 흐른다 → 스틱 = (-dx, +dy) (화면 y는 아래가 +, 스틱 y는 위가 +)
        sx, sy = -dx, dy
        if math.hypot(sx, sy) < min_shift:
            continue
        out[t] = 1 + int(round(math.atan2(sy, sx) / (math.pi / 4))) % 8
    return out


def evaluate(data_dirs):
    import os
    import train
    sessions, keys = train.load_sessions(data_dirs, os.path.join("runs", "idm", "cache"))
    names = [n for n, _ in train.PAD_BITS] + ["lt", "rt"]
    tot = {k: [0, 0, 0] for k in SLOTS}  # 맞힘, 놓침, 헛짚음 (지금 배치 기준)
    table = {k: {n: 0 for n in names} for k in SLOTS}  # 칸이 회색이 된 순간 ±3장 안에 새로 눌린 버튼
    det_n = {k: 0 for k in SLOTS}
    mv_ok = mv_near = mv_n = still_ok = still_n = 0
    for frames, acts, _ in sessions:
        fr = np.asarray(frames)
        pb = acts[:, 3].astype(np.int64)
        pressed = {n: (pb & bit) != 0 for n, bit in train.PAD_BITS}
        pressed["lt"], pressed["rt"] = acts[:, 8] > 30, acts[:, 9] > 30
        onsets = {n: on & ~np.r_[False, on[:-1]] for n, on in pressed.items()}
        for k, pred in slot_presses(fr).items():
            det_n[k] += int(pred.sum())
            for t in np.flatnonzero(pred):
                for n in names:
                    if onsets[n][max(0, t - 3):t + 4].any():
                        table[k][n] += 1
            onset = np.flatnonzero(onsets[SLOT_PAD[k]])
            used = set()
            for t in onset:
                hit = [p for p in np.flatnonzero(pred[max(0, t - 3):t + 4]) + max(0, t - 3) if p not in used]
                if hit:
                    tot[k][0] += 1; used.add(hit[0])
                else:
                    tot[k][1] += 1
            tot[k][2] += int(pred.sum()) - len(used)
        mc = motion_classes(fr)
        truth = np.array([train.stick_class(x, y) for x, y in acts[:, 4:6]])
        moving = truth > 0
        mv_n += int(moving.sum()); mv_ok += int((mc[moving] == truth[moving]).sum())
        d = np.abs(mc - truth) % 8
        mv_near += int((moving & (mc > 0) & ((d <= 1) | (d == 7))).sum())
        still_n += int((~moving).sum()); still_ok += int((mc[~moving] == 0).sum())
        print(f"세션 {len(fr)}장 처리", flush=True)
    print("\n[유물·물약] 지금 배치 기준: 실제 누른 횟수 중 맞힘 / 놓침 / 헛짚음")
    for k, (h, m, f) in tot.items():
        print(f"  {k}({SLOT_PAD[k]}): 맞힘 {h}, 놓침 {m}, 헛짚음 {f}" + (f"  → 찾은 비율 {h / max(1, h + m):.0%}" if h + m else ""))
    print("\n[버튼 배치 찾기] 칸이 회색이 된 순간에 같이 새로 눌린 버튼(많은 순서 3개)")
    for k in SLOTS:
        top = sorted(table[k].items(), key=lambda x: -x[1])[:3]
        print(f"  {k}: 회색 된 횟수 {det_n[k]} → " + ", ".join(f"{n} {c}번" for n, c in top))
    print(f"\n[이동] 움직일 때 방향 정확히 {mv_ok / max(1, mv_n):.0%}, 45도 옆까지 {mv_near / max(1, mv_n):.0%} / 가만있을 때 가만이라고 맞힘 {still_ok / max(1, still_n):.0%}")


def evaluate_combo(data_dirs, idm_path):
    """IDM만 / 규칙만 / 둘을 섞은 것 중 뭐가 나은지, IDM이 학습 때 안 본 검증 구간(1분 묶음 10개 중 1개)에서 비교한다."""
    import os
    import torch
    import train
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    st = torch.load(idm_path, map_location=dev)
    back, fwd = st["back"], st["fwd"]
    net = train.make_net(st.get("net", "small"), len(st["bin_names"]), [n for _, n in st["cats"]], st["stack"]).to(dev)
    net.load_state_dict(st["net"]); net.eval()
    sessions, _ = train.load_sessions(data_dirs, os.path.join("runs", "idm", "cache"))
    res = {"idm": [0, 0], "rule": [0, 0], "mix": [0, 0]}
    btn = {n: {"idm": [0, 0, 0], "mix": [0, 0, 0]} for n in ("lt", "b")}  # 맞힘, 놓침, 헛짚음
    for frames, acts, _ in sessions:
        fr = np.asarray(frames)
        ts = [t for t in range(back, len(fr) - fwd - 1) if (t // 600) % 10 == 9]
        if not ts:
            continue
        mc = motion_classes(fr)
        sat = slot_saturation(fr)
        rp = {}
        for k, name in (("potion", "lt"), ("a2", "b")):
            rp[name] = detect_presses(sat[k], np.mean([sat[o] for o in SLOTS if o != k], 0))
        for i in range(0, len(ts), 256):
            tt = ts[i:i + 256]
            x = np.stack([fr[t - back:t + fwd + 1] for t in tt])
            x = torch.from_numpy(x).permute(0, 1, 4, 2, 3).reshape(len(tt), -1, fr.shape[1], fr.shape[2]).to(dev)
            with torch.no_grad():
                pb, pc = net(x)
            pb = torch.sigmoid(pb).cpu().numpy(); pl = torch.softmax(pc[0], 1).cpu().numpy()
            for j, t in enumerate(tt):
                truth = train.stick_class(acts[t, 4], acts[t, 5])
                idm = int(pl[j].argmax()); rule = int(mc[t]); mix = idm if pl[j].max() >= 0.5 else rule
                for k, v in (("idm", idm), ("rule", rule), ("mix", mix)):
                    res[k][0] += int(v == truth); res[k][1] += 1
                b, _ = train.targets(acts[t], "pad", 0)
                for name, idx in (("lt", 14), ("b", 11)):
                    real = b[idx] > 0.5
                    p_idm = pb[j][idx] > 0.5
                    p_mix = p_idm or (pb[j][idx] > 0.2 and rp[name][max(0, t - 1):t + 2].any())
                    for k, v in (("idm", p_idm), ("mix", p_mix)):
                        c = btn[name][k]
                        if real and v: c[0] += 1
                        elif real: c[1] += 1
                        elif v: c[2] += 1
        print(f"세션 {len(fr)}장 처리", flush=True)
    print("\n[이동 방향 정확도, 검증 구간]")
    for k, lab in (("idm", "IDM만"), ("rule", "규칙만"), ("mix", "섞음(IDM 자신 없으면 규칙)")):
        print(f"  {lab}: {res[k][0] / max(1, res[k][1]):.0%}")
    print("\n[버튼, 검증 구간] 맞힘 / 놓침 / 헛짚음")
    for name in btn:
        for k, lab in (("idm", "IDM만"), ("mix", "섞음")):
            h, m, f = btn[name][k]
            print(f"  {name} {lab}: {h} / {m} / {f}")

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--eval", action="append", required=True)
    ap.add_argument("--idm", help="주면 IDM·규칙·섞은 것을 비교한다")
    a = ap.parse_args()
    if a.idm:
        evaluate_combo(a.eval, a.idm)
    else:
        evaluate(a.eval)
