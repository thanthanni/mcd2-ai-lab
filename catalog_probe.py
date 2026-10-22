"""창고 전체 목록 만들기(읽기만 함): 게임 메모리에 '지금 살아 있는' 모든 객체를 클래스별로 세고,
게임 쪽 클래스(엔진 기본 클래스 제외)의 속성 이름·종류를 전부 적고, 중요한 객체들은 값까지 적는다.

결과(서버로 보낼 때 gzip):
- catalog_classes.txt : 클래스 이름 / 살아 있는 개수 / 패키지 / 부모 3단계
- catalog_schema.txt  : 게임 쪽 클래스마다 속성 목록(+오프셋 종류 이름)
- catalog_values.txt  : 내 캐릭터·부품·컨트롤러·플레이어 상태·게임 상태·퀘스트/지도/탐험/진행 관련 객체의 속성 값
"""
from __future__ import annotations

import collections
import os
import sys
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from state_probe import find_ohs_app  # noqa: E402

ENGINE_PKG = ("Engine", "CoreUObject", "UMG", "Slate", "SlateCore", "Niagara", "NiagaraCore", "GameplayAbilities",
              "GameplayTags", "GameplayTasks", "AIModule", "NavigationSystem", "PhysicsCore", "Chaos", "MovieScene",
              "MovieSceneTracks", "LevelSequence", "AudioMixer", "AkAudio", "InputCore", "EnhancedInput", "Landscape",
              "Foliage", "MediaAssets", "CinematicCamera", "DeveloperSettings", "NetCore", "Renderer", "ClothingSystemRuntimeInterface",
              "AnimGraphRuntime", "AnimationCore", "Paper2D", "CommonUI", "CommonInput", "ModularGameplay", "IrisCore",
              "OnlineSubsystem", "OnlineSubsystemUtils", "PacketHandler", "AssetRegistry", "Water", "ChaosSolverEngine",
              "GeometryCollectionEngine", "FieldSystemEngine", "PCG", "MetasoundEngine", "MetasoundFrontend", "AudioExtensions")
VALUE_KEYS = ("Quest", "Map", "Marker", "Exploration", "Progress", "Objective", "Region", "Waypoint", "Teleport",
              "Shrine", "Statue", "Inventory", "Equipment", "Loadout", "Mission", "Adventure", "Unlock", "Discover")
VALUE_SKIP = ("W_", "GA_", "GE_", "GCN_", "AS_", "ABP_", "AM_", "BTTask", "BTService", "Default__", "NS_", "M_", "MI_",
              "T_", "SM_", "SK_", "DT_", "DA_", "CV_", "Curve")


def main():
    app = find_ohs_app()
    if not app:
        print("Offline Hero Sync 폴더를 못 찾았어.")
        return
    sys.path.insert(0, app)
    import winproc  # noqa
    import uemem    # noqa
    from state_reader import Reader
    from guide_probe import value
    ue = uemem.UE(winproc.Process(), rescan=True)
    r = Reader(ue)
    r.scan()
    t0 = time.time()

    count = collections.Counter()
    sample = {}
    for o in ue.iter_objects():
        try:
            if ue.objname(o).startswith("Default__"):
                continue
            c = ue.cls(o)
            count[c] += 1
            sample.setdefault(c, o)
        except Exception:
            continue

    def pkg(c):
        try:
            p = ue.outer(c)
            return ue.objname(p) if p else "?"
        except Exception:
            return "?"

    def is_game(c):
        p = pkg(c)
        name = p.rsplit("/", 1)[-1]
        return p.startswith("/Game/") or (p.startswith("/Script/") and name not in ENGINE_PKG)

    with open(os.path.join(HERE, "catalog_classes.txt"), "w", encoding="utf-8") as f:
        f.write(f"# 살아 있는 객체 {sum(count.values())}개, 클래스 {len(count)}종 ({time.strftime('%m-%d %H:%M')})\n")
        f.write("# 개수\t클래스\t패키지\t부모\n")
        for c, n in count.most_common():
            try:
                ch = r._chain(c)
                f.write(f"{n}\t{ch[0]}\t{pkg(c)}\t{' > '.join(ch[1:4])}\n")
            except Exception:
                continue

    with open(os.path.join(HERE, "catalog_schema.txt"), "w", encoding="utf-8") as f:
        for c, n in sorted(count.items(), key=lambda x: r._chain(x[0])[0] if r._chain(x[0]) else ""):
            try:
                if not is_game(c):
                    continue
                ch = r._chain(c)
                f.write(f"\n== {ch[0]}  ({' > '.join(ch[1:5])})  개수 {n}  {pkg(c)}\n")
                for name, pr in sorted(ue.oprops(sample[c]).items(), key=lambda x: x[1].offset):
                    extra = ""
                    if pr.kind == "StructProperty":
                        extra = ":" + ue.objname(pr.struct)
                    elif pr.kind == "ArrayProperty":
                        extra = ":" + pr.inner.kind + (":" + ue.objname(pr.inner.struct) if pr.inner.kind == "StructProperty" else "")
                    f.write(f"  +{pr.offset:#06x} {pr.kind}{extra} {name}\n")
            except Exception:
                continue

    def dump(f, o, title):
        f.write(f"\n== {title}  {ue.clsname(o)}  {ue.objname(o)[:80]}\n")
        for name, pr in sorted(ue.oprops(o).items(), key=lambda x: x[1].offset):
            if "Delegate" in pr.kind or pr.offset < 0x28:
                continue
            try:
                f.write(f"  +{pr.offset:#06x} {pr.kind:18s} {name} = {value(ue, o, pr)[:200]}\n")
            except Exception:
                pass

    with open(os.path.join(HERE, "catalog_values.txt"), "w", encoding="utf-8") as f:
        me = r.player
        if me:
            dump(f, me, "내 캐릭터")
            for name, pr in ue.oprops(me).items():          # 캐릭터에 붙은 부품들
                if pr.kind == "ObjectProperty":
                    try:
                        c = ue.q(me + pr.offset)
                        if c and ue.outer(c) == me:
                            dump(f, c, f"내 캐릭터 부품 {name}")
                    except Exception:
                        pass
        done = 0
        for c, o in sample.items():
            try:
                ch = r._chain(c)
                n = ch[0]
                if n.startswith(VALUE_SKIP):
                    continue
                if any(k in x for x in ch[:5] for k in ("PlayerController", "PlayerState", "GameState", "GameMode")) \
                        or any(k in n for k in VALUE_KEYS):
                    dump(f, o, f"{' > '.join(ch[:3])} (개수 {count[c]})")
                    done += 1
                    if done >= 400:
                        break
            except Exception:
                continue
        f.write(f"\n# {time.time() - t0:.0f}초 걸림\n")
    print("목록 완성:", time.time() - t0, "초")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        with open(os.path.join(HERE, "catalog_values.txt"), "a", encoding="utf-8") as f:
            f.write("오류: " + traceback.format_exc())
        traceback.print_exc()
