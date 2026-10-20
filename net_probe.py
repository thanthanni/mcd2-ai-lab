"""마던2가 지금 인터넷 서버에 붙어 있는지(온라인 플레이) 보기: 게임 프로세스의 TCP 연결 목록. 결과 net_probe.txt."""
import os
import subprocess

HERE = os.path.dirname(os.path.abspath(__file__))
out = subprocess.run(["tasklist", "/fi", "imagename eq Dungeons-Win64-Shipping.exe", "/fo", "csv", "/nh"],
                     capture_output=True, text=True, errors="ignore").stdout
pid = None
for line in out.splitlines():
    parts = [x.strip('"') for x in line.split('","')]
    if len(parts) > 1 and parts[1].isdigit():
        pid = parts[1]
lines = [f"게임 PID {pid}"]
ns = subprocess.run(["netstat", "-ano", "-p", "tcp"], capture_output=True, text=True, errors="ignore").stdout
lines += [l for l in ns.splitlines() if pid and l.split() and l.split()[-1] == pid]
ns6 = subprocess.run(["netstat", "-ano", "-p", "tcpv6"], capture_output=True, text=True, errors="ignore").stdout
lines += [l for l in ns6.splitlines() if pid and l.split() and l.split()[-1] == pid]
nu = subprocess.run(["netstat", "-ano", "-p", "udp"], capture_output=True, text=True, errors="ignore").stdout
lines += ["UDP:"] + [l for l in nu.splitlines() if pid and l.split() and l.split()[-1] == pid]
open(os.path.join(HERE, "net_probe.txt"), "w", encoding="utf-8").write("\n".join(lines))
print("\n".join(lines))
