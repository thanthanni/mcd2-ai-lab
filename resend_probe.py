"""ntfy 한도로 못 받은 결과 다시 보내기(10-23): 지정한 파일 내용과 수정 시각을 resend_probe_result.txt로, 사진 zip은 snaps_resend_probe.zip으로 복사.
runner가 새로 생긴 txt/snaps_*.zip을 보내 준다. 조작 없음."""
import os, shutil, sys, time
HERE = os.path.dirname(os.path.abspath(__file__))
names = sys.argv[1:] or ["controller_cycle_result.txt", "snaps_controller_cycle.zip", "last_job.txt", "status.txt"]
out = []
for n in names:
    p = os.path.join(HERE, n)
    if not os.path.exists(p):
        out.append(f"== {n}: 없음"); continue
    out.append(f"== {n}: {time.strftime('%m-%d %H:%M:%S', time.localtime(os.path.getmtime(p)))} {os.path.getsize(p)}B")
    if n.endswith(".zip"):
        shutil.copyfile(p, os.path.join(HERE, "snaps_resend_probe.zip"))
    else:
        out.append(open(p, encoding="utf-8", errors="replace").read()[-6000:])
open(os.path.join(HERE, "resend_probe_result.txt"), "w", encoding="utf-8").write("\n".join(out) + "\n")
