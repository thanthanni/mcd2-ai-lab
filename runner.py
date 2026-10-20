"""자동 반복 실행기: job.txt(저장소에서 받음)에 새 작업이 있으면 실행하고 결과를 보낸다.
작업이 없을 때 게임이 켜져 있으면 플레이 기록기를 뒤에서 켜 둔다(장훈이 플레이 = 모방학습 자료).

job.txt 한 줄: "<작업번호> <bat 이름> [반복 횟수] [daily]"  예) 20261019-1600 28_ppo.bat 6 daily
daily면 날짜가 바뀔 때마다 다시 한다(하루 한 번).
봇 작업은 장훈이가 PC를 안 쓸 때만 시작한다: 마우스를 3분 넘게 안 움직였고 진짜 패드가 꺼져 있을 때.
0_loop.bat이 1분마다 최신 파일을 받고 이걸 부른다.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LAST = os.path.join(HERE, "last_job.txt")
RECPID = os.path.join(HERE, "recorder.pid")
SKIP = {"idle_state.txt", "current.txt", "README.txt", "videos.txt", "data_path.txt", "job.txt", "last_job.txt", "sent.txt", "recorder.pid"}
IDLE_NEEDED = 180
# 안티치트가 있는 게임·런처: 이게 켜져 있으면 봇·기록기를 끄고 아무것도 안 한다(꺼지면 다시 평소대로)
ANTICHEAT = ["valorant-win64-shipping.exe", "valorant.exe", "league of legends.exe", "leagueclient.exe",
             "leagueclientux.exe", "riotclientservices.exe", "easyanticheat.exe", "easyanticheat_eos.exe",
             "beservice.exe", "beservice_x64.exe", "faceit.exe", "faceitclient.exe", "cs2.exe", "overwatch.exe",
             "r5apex.exe", "fortniteclient-win64-shipping.exe", "tslgame.exe", "lostark.exe", "blackdesert64.exe",
             "gamemon.des", "gamemon64.des", "xxd-0.xem", "x3.xem", "eldenring.exe", "destiny2.exe",
             "rainbowsix.exe", "pubg.exe", "fc_online.exe", "maplestory.exe", "dnf.exe", "sa.exe", "eternalreturn.exe"]


def running_names():
    out = subprocess.run(["tasklist", "/fo", "csv", "/nh"], capture_output=True, text=True, errors="ignore").stdout
    return {line.split('","')[0].strip('"').lower() for line in out.splitlines() if line}


def anticheat_running(names=None):
    names = names if names is not None else running_names()
    hit = [n for n in ANTICHEAT if n in names]
    return hit[0] if hit else None


def idle_seconds():
    class LII(ctypes.Structure):
        _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]
    li = LII()
    li.cbSize = ctypes.sizeof(LII)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
    return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000.0


IDLE_FILE = os.path.join(HERE, "idle_state.txt")


def cursor_idle_seconds():
    """마우스 커서가 마지막으로 움직인 뒤 지난 시간(1분마다 확인). GetLastInputInfo는 다른 프로그램이 보내는
    가짜 입력에도 초기화돼서(장훈 PC에서 50초마다 초기화됨) 커서 위치로 본다."""
    pt = wt.POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    now = time.time()
    try:
        x, y, t = open(IDLE_FILE).read().split()
        x, y, t = int(x), int(y), float(t)
    except (OSError, ValueError):
        x, y, t = None, None, now
    if (pt.x, pt.y) != (x, y):
        t = now
    with open(IDLE_FILE, "w") as f:
        f.write(f"{pt.x} {pt.y} {t}")
    return now - t


def game_running():
    out = subprocess.run(["tasklist", "/fi", "imagename eq Dungeons-Win64-Shipping.exe", "/nh"],
                         capture_output=True, text=True, errors="ignore").stdout
    return "Dungeons-Win64-Shipping" in out


def recorder_alive():
    try:
        pid = int(open(RECPID).read().strip())
    except (OSError, ValueError):
        return None
    out = subprocess.run(["tasklist", "/fi", f"pid eq {pid}", "/nh"], capture_output=True, text=True, errors="ignore").stdout
    return pid if str(pid) in out else None


def stop_recorder():
    pid = recorder_alive()
    if pid:
        subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True)
        print("[자동 실행] 플레이 기록기 멈춤(봇 작업 시작)", flush=True)
    try:
        os.remove(RECPID)
    except OSError:
        pass


def start_recorder():
    py = os.path.join(HERE, ".venv", "Scripts", "pythonw.exe")
    if not os.path.exists(py):
        py = os.path.join(HERE, ".venv", "Scripts", "python.exe")
    p = subprocess.Popen([py, os.path.join(HERE, "play_recorder.py")], cwd=HERE,
                         creationflags=0x00000008 | 0x00000200)   # DETACHED_PROCESS | NEW_PROCESS_GROUP
    with open(RECPID, "w") as f:
        f.write(str(p.pid))
    print("[자동 실행] 게임이 켜져 있어서 플레이 기록기를 켰어(네 플레이를 모방학습 자료로 모음)", flush=True)


def pending_job():
    try:
        job = open(os.path.join(HERE, "job.txt"), encoding="utf-8").read().split()
    except OSError:
        return None
    if len(job) < 2:
        return None
    jid, bat = job[0], job[1]
    reps = int(job[2]) if len(job) > 2 else 1
    if len(job) > 3 and job[3] == "daily":
        jid = f"{jid}@{time.strftime('%Y%m%d')}"
    last = open(LAST, encoding="utf-8").read().strip() if os.path.exists(LAST) else ""
    return None if jid == last else (jid, bat, reps)


def main():
    sys.path.insert(0, HERE)
    ac = anticheat_running()
    if ac:                                               # 안티치트 게임 중: 기록기 끄고 쉼
        if recorder_alive():
            stop_recorder()
        print(f"[자동 실행] {ac} 실행 중이라 쉬는 중(꺼지면 다시 시작)", flush=True)
        return
    job = pending_job()
    if job and not game_running():
        return                                           # 마던2가 꺼져 있으면(딴 게임 중 등) 아무것도 안 함
    if job:
        import gamewin
        idle = cursor_idle_seconds()
        quick = "probe" in job[1]                        # 읽기만 하는 탐색 작업은 조작을 안 하니 바로 실행
        if not quick and (idle < IDLE_NEEDED or gamewin.pads_connected()):
            print(f"[자동 실행] 작업 {job[1]} 대기 중: PC를 쓰는 중이라(마우스 {idle:.0f}초 전에 움직임, "
                  f"패드 {'켜짐' if gamewin.pads_connected() else '꺼짐'}) 3분 안 쓰고 패드 끄면 시작", flush=True)
            if game_running() and not recorder_alive():
                start_recorder()
            return
        jid, bat, reps = job
        stop_recorder()
        with open(LAST, "w", encoding="utf-8") as f:      # 먼저 적어서 실패해도 무한 반복 안 함
            f.write(jid)
        import uploader
        for k in range(reps):
            print(f"[자동 실행] 작업 {jid} {bat} ({k + 1}/{reps})", flush=True)
            t0 = time.time()
            env = dict(os.environ, NEXT=bat)
            p = subprocess.Popen(["cmd", "/c", bat], cwd=HERE, env=env)
            stopped = None
            import gamewin
            while p.poll() is None:                           # 감시: 안티치트 게임이 켜지거나 진짜 패드가 켜지면 봇을 바로 끔
                time.sleep(5)
                ac = anticheat_running()
                # 봇이 만든 가상 패드도 XInput에 1개로 잡히니까, 2개 이상일 때만 '진짜 패드가 켜짐'
                if ac or gamewin.pads_connected() >= 2:
                    stopped = ac or "패드 켜짐"
                    subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True)
                    print(f"[자동 실행] {stopped} → 봇을 멈췄어", flush=True)
                    break
            names = [os.path.basename(p) for p in glob.glob(os.path.join(glob.escape(HERE), "*.txt")) +
                     glob.glob(os.path.join(glob.escape(HERE), "*.jsonl"))
                     if os.path.getmtime(p) > t0 and os.path.basename(p) not in SKIP
                     and not os.path.basename(p).startswith("play_")]
            n = sum(uploader.send_file(name, title=f"{jid} {k + 1}/{reps}") for name in names)
            print(f"[자동 실행] 결과 {n}개 보냄", flush=True)
            if not stopped and time.time() - t0 < 120:        # 2분도 못 가고 끝났으면 오류: 작업을 '안 한 것'으로 되돌려 나중에 다시
                try:
                    os.remove(LAST)
                except OSError:
                    pass
                print("[자동 실행] 작업이 바로 끝나서(오류) 다음에 다시 시도할게", flush=True)
                break
            if stopped or gamewin.pads_connected():           # 멈췄거나 장훈이가 돌아왔으면 남은 반복은 그만(봇이 끝나면 가상 패드는 사라짐)
                print("[자동 실행] 남은 반복은 멈춤", flush=True)
                break
        return
    if game_running() and not recorder_alive():
        start_recorder()


if __name__ == "__main__":
    main()
