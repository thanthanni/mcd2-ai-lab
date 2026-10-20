"""자동 반복 실행기: job.txt(저장소에서 받음)에 새 작업이 있으면 실행하고 결과를 보낸다.
작업이 없을 때 게임이 켜져 있으면 플레이 기록기를 뒤에서 켜 둔다(장훈이 플레이 = 모방학습 자료).

job.txt 한 줄: "<작업번호> <bat 이름> [반복 횟수] [daily]"  예) 20261019-1600 28_ppo.bat 6 daily
daily면 날짜가 바뀔 때마다 다시 한다(하루 한 번).
봇 작업은 장훈이가 PC를 안 쓸 때만 시작한다: 키보드·마우스 5분 넘게 안 만졌고 진짜 패드가 꺼져 있을 때.
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
SKIP = {"current.txt", "README.txt", "videos.txt", "data_path.txt", "job.txt", "last_job.txt", "sent.txt", "recorder.pid"}
IDLE_NEEDED = 300


def idle_seconds():
    class LII(ctypes.Structure):
        _fields_ = [("cbSize", wt.UINT), ("dwTime", wt.DWORD)]
    li = LII()
    li.cbSize = ctypes.sizeof(LII)
    ctypes.windll.user32.GetLastInputInfo(ctypes.byref(li))
    return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) / 1000.0


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
    job = pending_job()
    if job:
        import gamewin
        idle = idle_seconds()
        if idle < IDLE_NEEDED or gamewin.pads_connected():
            print(f"[자동 실행] 작업 {job[1]} 대기 중: PC를 쓰는 중이라(키보드·마우스 {idle:.0f}초 전 사용, "
                  f"패드 {'켜짐' if gamewin.pads_connected() else '꺼짐'}) 5분 안 쓰고 패드 끄면 시작", flush=True)
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
            subprocess.run(["cmd", "/c", bat], cwd=HERE, env=env)
            names = [os.path.basename(p) for p in glob.glob(os.path.join(glob.escape(HERE), "*.txt")) +
                     glob.glob(os.path.join(glob.escape(HERE), "*.jsonl"))
                     if os.path.getmtime(p) > t0 and os.path.basename(p) not in SKIP
                     and not os.path.basename(p).startswith("play_")]
            n = sum(uploader.send_file(name, title=f"{jid} {k + 1}/{reps}") for name in names)
            print(f"[자동 실행] 결과 {n}개 보냄", flush=True)
            import gamewin
            if gamewin.pads_connected():                      # 장훈이가 패드를 켜면(돌아와서 플레이) 남은 반복은 그만
                print("[자동 실행] 패드가 켜져서 남은 반복은 멈춤", flush=True)
                break
        return
    if game_running() and not recorder_alive():
        start_recorder()


if __name__ == "__main__":
    main()
