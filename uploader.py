"""결과 파일을 헤르타 쪽으로 보내기(0_auto.bat에 적힌 ntfy 주소 사용). 보낸 파일은 sent.txt에 적어 두고 다시 안 보낸다.
사용: python uploader.py [파일 패턴 ...]   (기본: play_*.jsonl)"""
from __future__ import annotations

import glob
import os
import re
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SENT = os.path.join(HERE, "sent.txt")


def topic():
    try:
        m = re.search(r"ntfy\.sh/(mcd2lab-[0-9a-f]+)", open(os.path.join(HERE, "0_auto.bat"), encoding="utf-8", errors="ignore").read())
        return m.group(1) if m else None
    except OSError:
        return None


def send_pending(patterns=("play_*.jsonl",), quiet=False):
    t = topic()
    if not t:
        if not quiet:
            print("0_auto.bat에서 보낼 주소를 못 찾았어.")
        return 0
    sent = set(open(SENT, encoding="utf-8").read().split()) if os.path.exists(SENT) else set()
    n = 0
    if not quiet:
        print("폴더:", HERE)
        print("이미 보낸 것:", sorted(sent))
    for pat in patterns:
        found = sorted(glob.glob(os.path.join(glob.escape(HERE), pat)))
        if not quiet:
            print(f"{pat}: {len(found)}개 찾음", [os.path.basename(f) for f in found])
        for p in found:
            name = os.path.basename(p)
            if name in sent or os.path.getsize(p) == 0:
                continue
            if os.path.getsize(p) > 14_000_000:
                print(f"{name}: 너무 커서 못 보냄(14MB 넘음)")
                continue
            req = urllib.request.Request(f"https://ntfy.sh/{t}", data=open(p, "rb").read(), method="PUT",
                                         headers={"Filename": name, "Title": "upload"})
            try:
                urllib.request.urlopen(req, timeout=120).read()
            except Exception as e:
                print(f"{name}: 보내기 실패 {e}")
                continue
            with open(SENT, "a", encoding="utf-8") as f:
                f.write(name + "\n")
            n += 1
            if not quiet:
                print(f"보냄: {name}")
    return n


def send_file(name, title="result"):
    """파일 하나를 바로 보냄(보낸 기록 없이). 성공하면 1."""
    t = topic()
    p = os.path.join(HERE, name)
    if not t or not os.path.exists(p) or os.path.getsize(p) == 0 or os.path.getsize(p) > 14_000_000:
        return 0
    req = urllib.request.Request(f"https://ntfy.sh/{t}", data=open(p, "rb").read(), method="PUT",
                                 headers={"Filename": name, "Title": title})
    try:
        urllib.request.urlopen(req, timeout=120).read()
        return 1
    except Exception as e:
        print(f"{name}: 보내기 실패 {e}")
        return 0


if __name__ == "__main__":
    k = send_pending(tuple(sys.argv[1:]) or ("play_*.jsonl",))
    print(f"보낸 파일 {k}개")
