"""상태 기반 모방학습(서버에서 학습, PC에선 numpy로 실행).

입력: play_*.jsonl (play_recorder.py). 상태 숫자(내 정보·가까운 적 5·안내선 3점·퀘스트 2) → 행동.
행동: 이동 방향 9가지(멈춤 + 8방향, 다음 0.1초의 실제 속도로 정함 — 패드든 마우스든 같음)
      + 버튼 누름(X 근접, A 점프/상호작용, LB 구르기, B·RB·Y 유물, L3 안내선, RT 활(누르고 있음), LT 물약).
결과: bc_model.json (가중치, numpy로 바로 씀) + 평가 출력.
사용: uv run --with scikit-learn --with numpy python bc_state.py <jsonl 파일들...>
"""
from __future__ import annotations

import json
import math
import sys

import numpy as np

BTN = {"X": 0x4000, "A": 0x1000, "LB": 0x100, "B": 0x2000, "RB": 0x200, "Y": 0x8000, "L3": 0x40}
HOLD = {"RT": 6, "LT": 5}            # pad 배열 위치(트리거 > 0.5면 누름)
OUTS = list(BTN) + list(HOLD)
NF, NG, NQ = 5, 3, 2
S = 2000.0                           # 거리 정규화


def feats(r):
    me = r["me"]
    hp, hpm = me["hp"]
    v = [hpm and hp / hpm or 0, (me["soul"] or 0) / 170, me["pot"] or 0, me["roll"] or 0, (me["ammo"] or 0) / 15,
         me["v"][0] / 700, me["v"][1] / 700]
    for i in range(NF):
        if i < len(r["foes"]):
            d, dx, dy, dz, h, m, n, age = r["foes"][i]
            v += [1, dx / S, dy / S, dz / S, d / S, (m and h / m) or 0, 1 if (age is None or age < 0.5) else 0,
                  1 if "Wolf" in n else 0]
        else:
            v += [0] * 8
    g = r.get("guide") or []
    for i in range(NG):
        v += ([1, g[i][0] / S, g[i][1] / S, g[i][2] / S] if i < len(g) else [0, 0, 0, 0])
    q = r.get("quest") or []
    for i in range(NQ):
        v += ([1, q[i][1] / S, q[i][2] / S, q[i][3] / S, q[i][0] / S] if i < len(q) else [0] * 5)
    return v


def rotate(X, M, k):
    """장면 전체를 k*45도 돌림(게임 규칙은 방향과 무관). 특징 안의 (x, y) 쌍과 이동 방향 번호를 같이 돌린다."""
    a = k * math.pi / 4
    c, s_ = math.cos(a), math.sin(a)
    X = X.copy()
    pairs = [(5, 6)]                                   # 내 속도
    base = 7
    for i in range(NF):
        pairs.append((base + 8 * i + 1, base + 8 * i + 2))
    base += 8 * NF
    for i in range(NG):
        pairs.append((base + 4 * i + 1, base + 4 * i + 2))
    base += 4 * NG
    for i in range(NQ):
        pairs.append((base + 5 * i + 1, base + 5 * i + 2))
    for xi, yi in pairs:
        x, y = X[:, xi].copy(), X[:, yi].copy()
        X[:, xi], X[:, yi] = c * x - s_ * y, s_ * x + c * y
    M = np.where(M == 0, 0, (M - 1 + k) % 8 + 1)
    return X, M


def move_label(v):
    sp = math.hypot(v[0], v[1])
    if sp < 120:
        return 0
    a = math.atan2(v[1], v[0])
    return 1 + int(round(a / (math.pi / 4))) % 8      # 1..8: 세계 좌표 기준 8방향


def load(paths):
    X, M, B = [], [], []
    for p in paths:
        rows = [json.loads(l) for l in open(p, encoding="utf-8")]
        prev_btn = 0
        for i in range(len(rows) - 1):
            r, nx = rows[i], rows[i + 1]
            if "me" not in r or "me" not in nx or not r.get("pad"):
                prev_btn = 0
                continue
            if r["me"]["hp"][0] <= 0:
                continue
            pad = r["pad"]
            b = pad[0]
            lab = [1 if (b & m and not prev_btn & m) else 0 for m in BTN.values()]   # 이번에 새로 누른 것
            lab += [1 if pad[k] > 0.5 else 0 for k in HOLD.values()]
            prev_btn = b
            X.append(feats(r))
            M.append(move_label(nx["me"]["v"]))
            B.append(lab)
    return np.array(X, dtype=np.float32), np.array(M), np.array(B)


def export(clf, path_key, out):
    out[path_key] = {"W": [w.tolist() for w in clf.coefs_], "b": [b.tolist() for b in clf.intercepts_],
                     "classes": clf.classes_.tolist() if hasattr(clf, "classes_") else None}


def main():
    from sklearn.neural_network import MLPClassifier
    paths = sys.argv[1:]
    X, M, B = load(paths)
    n = len(X)
    cut = int(n * 0.8)                       # 시간 순서로 앞 80% 학습, 뒤 20% 평가
    print(f"샘플 {n}개, 특징 {X.shape[1]}개")
    # 학습 구간만 8방향으로 돌려 8배로 불림(평가 구간은 원래 그대로)
    parts = [rotate(X[:cut], M[:cut], k) for k in range(8)]
    XA = np.concatenate([p[0] for p in parts])
    MA = np.concatenate([p[1] for p in parts])
    BA = np.concatenate([B[:cut]] * 8)
    print(f"학습용으로 불린 샘플 {len(XA)}개")
    mv = MLPClassifier(hidden_layer_sizes=(128, 64), max_iter=300, early_stopping=True, random_state=0)
    mv.fit(XA, MA)
    acc = (mv.predict(X[cut:]) == M[cut:]).mean()
    base = (M[cut:] == np.bincount(M[:cut]).argmax()).mean()
    print(f"이동 방향 정확도 {acc:.2f} (늘 같은 답만 하면 {base:.2f})")
    bt = MLPClassifier(hidden_layer_sizes=(128, 64), max_iter=300, early_stopping=True, random_state=0)
    bt.fit(XA, BA)
    P = bt.predict_proba(X[cut:])
    thr = {}
    for j, name in enumerate(OUTS):
        y = B[cut:, j]
        best = (0.0, 0.5)
        for t in np.arange(0.05, 0.95, 0.05):
            pr = P[:, j] > t
            tp = (pr & (y == 1)).sum()
            f1 = 2 * tp / (pr.sum() + y.sum()) if (pr.sum() + y.sum()) else 0
            best = max(best, (f1, float(t)))
        thr[name] = best[1]
        print(f"  {name}: 실제 {int(y.sum())}번, F1 {best[0]:.2f} (기준 {best[1]:.2f})")
    out = {"feat": X.shape[1], "outs": OUTS, "thr": thr, "nf": NF, "ng": NG, "nq": NQ}
    export(mv, "move", out)
    export(bt, "btn", out)
    json.dump(out, open("bc_model.json", "w"))
    print("저장: bc_model.json")


if __name__ == "__main__":
    main()
