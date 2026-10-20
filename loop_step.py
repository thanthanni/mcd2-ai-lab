"""0_loop.bat이 1분마다 부르는 한 걸음: (1) 안티치트 게임 중이면 아무것도 안 하고 끝(다운로드도 안 함)
(2) 아니면 저장소 최신 파일을 받아 덮어쓰고 (3) runner.main()으로 작업 확인·실행.
파이썬 파일은 시작할 때 통째로 읽히니까 실행 중에 자기 자신을 덮어써도 안전하다."""
from __future__ import annotations

import io
import os
import sys
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
URL = "https://codeload.github.com/thanthanni/mcd2-ai-lab/zip/refs/heads/main"
KEEP = {"0_auto.bat", "0_loop.bat", "last_job.txt", "sent.txt", "recorder.pid", "idle_state.txt"}   # PC에만 있는 파일은 안 덮음


def update():
    data = urllib.request.urlopen(URL, timeout=60).read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            name = info.filename.split("/", 1)[-1]
            if not name or name.endswith("/") or "/" in name or name in KEEP:
                continue
            dst = os.path.join(HERE, name)
            body = z.read(info)
            try:
                if os.path.exists(dst) and open(dst, "rb").read() == body:
                    continue
            except OSError:
                pass
            with open(dst, "wb") as f:
                f.write(body)


def ensure_packages():
    """봇에 필요한 패키지가 빠져 있으면(.venv를 새로 만든 경우 등) uv로 설치."""
    import importlib.util
    import subprocess
    need = [p for p in ("vgamepad", "numpy", "torch") if importlib.util.find_spec(p) is None]
    if not need:
        return
    uv = os.path.join(os.path.expanduser("~"), ".local", "bin", "uv.exe")
    print(f"[자동 실행] 빠진 패키지 설치: {need}", flush=True)
    for p in need:
        args = [uv, "pip", "install", "--python", os.path.join(HERE, ".venv"), p]
        if p == "torch":
            args += ["--index-url", "https://download.pytorch.org/whl/cu128"]
        subprocess.run(args, cwd=HERE)


def main():
    sys.path.insert(0, HERE)
    import runner
    ac = runner.anticheat_running()
    if ac:
        if runner.recorder_alive():
            runner.stop_recorder()
        print(f"[자동 실행] {ac} 실행 중이라 꺼 둠(파일 받기도 안 함). 끄면 다시 확인해.", flush=True)
        return
    try:
        update()
    except Exception as e:
        print("[자동 실행] 최신 파일 받기 실패(지난 파일로 계속):", e, flush=True)
    ensure_packages()
    import importlib
    importlib.reload(runner)                   # 방금 받은 runner로 실행
    runner.main()


if __name__ == "__main__":
    main()
