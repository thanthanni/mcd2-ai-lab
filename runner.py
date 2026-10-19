"""자동 반복 실행기: job.txt(저장소에서 받음)에 새 작업이 있으면 실행하고 결과를 보낸다.

job.txt 한 줄: "<작업번호> <bat 이름> [반복 횟수]"  예) 20261019-1600 15_learn_bot.bat 3
이미 한 작업번호(last_job.txt)면 아무것도 안 한다. 0_loop.bat이 1분마다 최신 파일을 받고 이걸 부른다.
"""
from __future__ import annotations

import glob
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
LAST = os.path.join(HERE, "last_job.txt")
SKIP = {"current.txt", "README.txt", "videos.txt", "data_path.txt", "job.txt", "last_job.txt", "sent.txt"}


def main():
    try:
        job = open(os.path.join(HERE, "job.txt"), encoding="utf-8").read().split()
    except OSError:
        return
    if len(job) < 2:
        return
    jid, bat = job[0], job[1]
    reps = int(job[2]) if len(job) > 2 else 1
    last = open(LAST, encoding="utf-8").read().strip() if os.path.exists(LAST) else ""
    if jid == last:
        return
    with open(LAST, "w", encoding="utf-8") as f:      # 먼저 적어서 실패해도 무한 반복 안 함
        f.write(jid)
    sys.path.insert(0, HERE)
    import uploader
    for k in range(reps):
        print(f"[자동 실행] 작업 {jid} {bat} ({k + 1}/{reps})", flush=True)
        t0 = time.time()
        env = dict(os.environ, NEXT=bat)
        subprocess.run(["cmd", "/c", bat], cwd=HERE, env=env)
        names = [os.path.basename(p) for p in glob.glob(os.path.join(glob.escape(HERE), "*.txt")) +
                 glob.glob(os.path.join(glob.escape(HERE), "*.jsonl"))
                 if os.path.getmtime(p) > t0 and os.path.basename(p) not in SKIP]
        n = 0
        for name in names:
            n += uploader.send_file(name, title=f"{jid} {k + 1}/{reps}")
        print(f"[자동 실행] 결과 {n}개 보냄", flush=True)


if __name__ == "__main__":
    main()
