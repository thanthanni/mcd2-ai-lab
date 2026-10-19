"""모방학습용 플레이 기록기(읽기만 함). 장훈이가 평소처럼 플레이하는 동안 초당 10번
게임 상태(메모리)와 입력(진짜 패드·키보드·마우스)을 같이 적는다. 게임에 아무것도 보내지 않는다.

- 게임을 끄면 자동으로 끝난다(아니면 이 창에서 Ctrl+C → Y/N 물으면 N).
- 10분마다 play_날짜_시각_번호.jsonl 파일을 새로 만든다(자동 업로드 크기 제한 때문).
- 오프라인 사본 캐릭터로만 플레이할 것.

한 줄 = {"t", "me": 위치·속도·방향·체력·영혼·물약·구르기·화살, "foes": 가까운 적 8마리(상대 위치·체력·보임),
         "guide": 안내선 다음 점 4개(상대 위치), "quest": 가까운 퀘스트 대상 3개(상대 위치),
         "pad": 버튼 비트·스틱·트리거, "keys": 눌린 키·마우스 버튼, "cur": 마우스 화면 좌표, "cam": 카메라}
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import json
import math
import os
import sys
import threading
import time
import traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from state_probe import find_ohs_app  # noqa: E402

HZ = 10
CHUNK = 600            # 초, 파일 하나 길이
u32 = ctypes.WinDLL("user32")

# 기록할 키: 마우스 왼/오/가운데, 스페이스, 쉬프트, 1~3, Q, E, R, F, J, M, I, X, Tab
VKS = {"LMB": 0x01, "RMB": 0x02, "MMB": 0x04, "SPACE": 0x20, "SHIFT": 0x10, "1": 0x31, "2": 0x32, "3": 0x33,
       "Q": 0x51, "E": 0x45, "R": 0x52, "F": 0x46, "J": 0x4A, "M": 0x4D, "I": 0x49, "X": 0x58, "TAB": 0x09}


class XS(ctypes.Structure):
    _fields_ = [("packet", wt.DWORD), ("buttons", wt.WORD), ("lt", ctypes.c_ubyte), ("rt", ctypes.c_ubyte),
                ("lx", ctypes.c_short), ("ly", ctypes.c_short), ("rx", ctypes.c_short), ("ry", ctypes.c_short)]


def read_pad(xi):
    s = XS()
    for i in range(4):
        if xi.XInputGetState(i, ctypes.byref(s)) == 0:
            return [s.buttons, round(s.lx / 32767, 2), round(s.ly / 32767, 2), round(s.rx / 32767, 2),
                    round(s.ry / 32767, 2), round(s.lt / 255, 2), round(s.rt / 255, 2)]
    return None


def main():
    app = find_ohs_app()
    if not app:
        print("Offline Hero Sync 폴더를 못 찾았어.")
        return
    sys.path.insert(0, app)
    import winproc  # noqa
    import uemem    # noqa
    import screen
    from state_reader import Reader
    proc = winproc.Process()
    ue = uemem.UE(proc, rescan=True)
    r = Reader(ue)
    r.scan()
    lock = threading.Lock()
    stop = {"v": False}

    def rescan():
        while not stop["v"]:
            time.sleep(3)
            try:
                f = Reader(ue)
                f.chain, f.off = r.chain, r.off
                f.scan()
                with lock:
                    r.player = f.player or r.player
                    r.mobs, r.atr, r.guides, r.trail, r.quest_objs = f.mobs, f.atr, f.guides, f.trail, f.quest_objs
            except Exception:
                pass

    threading.Thread(target=rescan, daemon=True).start()
    try:
        xi = ctypes.WinDLL("xinput1_4")
    except OSError:
        xi = None
    try:
        cam = screen.Camera(ue).find()
    except Exception:
        cam = None
    try:                      # 지난번에 못 보낸 기록이 있으면 먼저 보냄
        import uploader
        k = uploader.send_pending(quiet=True)
        if k:
            print(f"지난 기록 {k}개를 보냈어.")
    except Exception:
        pass
    print("기록 시작. 평소처럼 플레이해. 게임을 끄면 자동으로 끝나.", flush=True)
    t0 = time.time()
    n_lines, fh, chunk_i, chunk_t = 0, None, 0, 0.0
    stamp = time.strftime("%Y%m%d_%H%M")
    try:
        while True:
            tick = time.time()
            if not ue.alive():
                break
            if fh is None or tick - chunk_t > CHUNK:
                if fh:
                    fh.close()
                chunk_i += 1
                fh = open(os.path.join(HERE, f"play_{stamp}_{chunk_i}.jsonl"), "w", encoding="utf-8")
                chunk_t = tick
            try:
                with lock:
                    me_o, mobs, quest = r.player, dict(r.mobs), dict(r.quest_objs)
                x, y, z = r.loc(me_o)
                vel = r.vel(me_o)
                hp, hpmax = r.hp(me_o)
                row = {"t": round(tick - t0, 2), "me": {
                    "p": [round(x), round(y), round(z)], "v": [round(vel[0]), round(vel[1]), round(vel[2])],
                    "yaw": round(r.yaw(me_o)), "hp": [round(hp or 0, 1), round(hpmax or 0, 1)],
                    "soul": round(r.attr(me_o, "ATR_Soul", "Souls") or 0, 1),
                    "pot": r.attr(me_o, "ATR_Health", "HealthPotionCharges"),
                    "roll": r.attr(me_o, "ATR_Movement", "RollCharges"),
                    "ammo": r.attr(me_o, "ATR_RangedAttack", "RangedAttackAmmoCount")}}
                foes = []
                for o, n in mobs.items():
                    try:
                        mx, my, mz = r.loc(o)
                        d = math.hypot(mx - x, my - y)
                        if d > 1500:
                            continue
                        h, m = r.hp(o)
                        if h is None or h <= 0:
                            continue
                        try:
                            age = round(r.render_age(o), 1)
                        except Exception:
                            age = None
                        foes.append([round(d), round(mx - x), round(my - y), round(mz - z), round(h, 1), round(m or 0, 1), n, age])
                    except Exception:
                        continue
                foes.sort()
                row["foes"] = foes[:8]
                try:
                    path, _ = r.guide_path((x, y))
                    if path:
                        dd = [math.hypot(p[0] - x, p[1] - y) for p in path]
                        i = dd.index(min(dd))
                        row["guide"] = [[round(p[0] - x), round(p[1] - y), round(p[2] - z)] for p in path[i:i + 4]]
                except Exception:
                    pass
                qs = []
                for o, n in quest.items():
                    try:
                        p = r.loc(o)
                        d = math.hypot(p[0] - x, p[1] - y)
                        if d < 2500:
                            qs.append([round(d), round(p[0] - x), round(p[1] - y), round(p[2] - z), n])
                    except Exception:
                        continue
                row["quest"] = sorted(qs)[:3]
            except Exception as e:
                row = {"t": round(tick - t0, 2), "err": str(e)[:80]}
            if xi:
                row["pad"] = read_pad(xi)
            row["keys"] = [k for k, vk in VKS.items() if u32.GetAsyncKeyState(vk) & 0x8000]
            pt = wt.POINT()
            u32.GetCursorPos(ctypes.byref(pt))
            row["cur"] = [pt.x, pt.y]
            if cam and n_lines % 50 == 0:
                try:
                    c = cam.read()
                    row["cam"] = [round(v) for v in c["loc"]] + [round(c["pitch"], 1), round(c["yaw"], 1), round(c["fov"], 1)]
                except Exception:
                    pass
            fh.write(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n")
            n_lines += 1
            if n_lines % 50 == 0:
                fh.flush()
                print(f"\r기록 {n_lines}줄 ({(tick - t0) / 60:.1f}분)   ", end="", flush=True)
            time.sleep(max(0, 1 / HZ - (time.time() - tick)))
    except KeyboardInterrupt:
        pass
    finally:
        stop["v"] = True
        if fh:
            fh.close()
    print(f"\n기록 끝: {n_lines}줄, {(time.time() - t0) / 60:.1f}분")
    try:                      # 창을 바로 닫아도 되게, 기록 파일은 여기서 직접 보낸다
        import uploader
        print(f"보낸 기록 파일: {uploader.send_pending()}개")
    except Exception as e:
        print("보내기 실패:", e)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        traceback.print_exc()
