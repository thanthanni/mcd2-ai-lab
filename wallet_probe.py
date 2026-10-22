"""에메랄드·경험치가 메모리 어디에 있는지 찾기(읽기만 함). 결과 wallet_probe.txt.

1) 내 캐릭터의 ATR_* 묶음 이름과 숫자 전부
2) 클래스 이름(부모 포함)에 Player·Inventory·Wallet·Currency·Progress·Hero가 들어간 객체에서,
   속성 이름에 Emerald·Currency·Gold·Money·Wallet·Gem·XP·Experience·Level·Count·Amount가 들어간 값
"""
from __future__ import annotations

import os
import sys
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "wallet_probe.txt")
sys.path.insert(0, HERE)
from state_probe import find_ohs_app  # noqa: E402

CLS = ("Player", "Inventory", "Wallet", "Currency", "Progress", "Hero", "Character")
PROP = ("Emerald", "Currency", "Gold", "Money", "Wallet", "Gem", "XP", "Experience", "Level", "Amount", "Balance")
SKIP = ("W_", "GA_", "GE_", "GCN_", "AS_", "ABP_", "AM_", "BTTask", "Default__")
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
    me = r.player
    log("내 캐릭터:", ue.clsname(me) if me else "없음")
    log("\n[내 ATR 묶음]")
    for n, a in sorted(r.atr.get(me, {}).items()):
        vals = []
        for name, pr in sorted(ue.oprops(a).items(), key=lambda x: x[1].offset):
            if pr.kind == "StructProperty":
                try:
                    vals.append(f"{name}={ue.f32(a + pr.offset + 0xC):g}")
                except Exception:
                    pass
        log(f"  {n}: {', '.join(vals)[:400]}")

    log("\n[돈·경험치 후보 속성]")
    shown = 0
    for o in ue.iter_objects():
        try:
            if ue.objname(o).startswith(SKIP):
                continue
            chain = r._chain(ue.cls(o))
            n = chain[0] if chain else ""
            if not n or n.startswith(SKIP) or not any(any(k in c for k in CLS) for c in chain[:6]):
                continue
            hits = []
            for name, pr in sorted(ue.oprops(o).items(), key=lambda x: x[1].offset):
                if any(k.lower() in name.lower() for k in PROP) and "Delegate" not in pr.kind:
                    hits.append(f"+{pr.offset:#06x} {pr.kind} {name} = {value(ue, o, pr)[:120]}")
            if hits:
                log(f"\n== {n} ({' > '.join(chain[1:4])}) {ue.objname(o)[:60]}")
                for h in hits[:25]:
                    log("  " + h)
                shown += 1
                if shown >= 60:
                    break
        except Exception:
            continue


if __name__ == "__main__":
    try:
        main()
    except Exception:
        log("오류:", traceback.format_exc())
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print("\n결과를 저장했어:", OUT)
