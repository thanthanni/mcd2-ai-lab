"""게임 지식(knowledge/mobs.json에서 뽑은 mobs_compact.json)을 상태 숫자에 덧붙인다.
가까운 적 5마리마다 [근접, 원거리, 자폭, 소환·지원, 위험도/5, 거리 둬야 함] 6개 → 기본 69 + 30 = 99."""
from __future__ import annotations

import json
import os

import bc_state

HERE = os.path.dirname(os.path.abspath(__file__))
_TABLE = None
_CACHE = {}
NK = 6
NOBS = 69 + bc_state.NF * NK


def _table():
    global _TABLE
    if _TABLE is None:
        p = os.path.join(HERE, "mobs_compact.json")
        _TABLE = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else []
    return _TABLE


def info(cls_name):
    """클래스 이름(BP_Creeper_Charged_C 등) → 지식 dict(모르면 None). 가장 긴 이름 조각이 맞는 걸 쓴다."""
    if cls_name in _CACHE:
        return _CACHE[cls_name]
    key = cls_name.lower().replace("_", "").replace("bp", "", 1)
    hit = None
    for tok, f, name in _table():
        if tok in key:
            hit = f
            break
    _CACHE[cls_name] = hit
    return hit


def vec(cls_name):
    f = info(cls_name)
    if not f:
        return [0, 0, 0, 0, 0.4, 0]
    return [f["melee"], f["ranged"], f["explode"], f["summon"], (f["danger"] or 2) / 5, f["keep"]]


def feats(row):
    v = bc_state.feats(row)
    for i in range(bc_state.NF):
        v += vec(row["foes"][i][6]) if i < len(row["foes"]) else [0] * NK
    return v
