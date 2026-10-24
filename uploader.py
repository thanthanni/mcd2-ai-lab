"""결과 파일을 헤르타 쪽으로 보내기(0_auto.bat에 적힌 ntfy 주소 사용). 보낸 파일은 sent.txt에 적어 두고 다시 안 보낸다.
사용: python uploader.py [파일 패턴 ...]   (기본: play_*.jsonl)"""
from __future__ import annotations

import glob
import gzip
import os
import re
import sys
import time
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SENT = os.path.join(HERE, "sent.txt")


def topic():
    try:
        m = re.search(r"ntfy\.sh/(mcd2lab-[0-9a-f]+)", open(os.path.join(HERE, "0_auto.bat"), encoding="utf-8", errors="ignore").read())
        return m.group(1) if m else None
    except OSError:
        return None


def _body(p, name):
    """100KB 넘는 파일은 gzip으로 줄여서 보냄(ntfy 하루 용량 한도 때문, 10-22). (내용, 보낼 이름)"""
    data = open(p, "rb").read()
    if len(data) > 100_000 and not name.endswith((".gz", ".zip", ".jpg", ".png")):
        return gzip.compress(data, 6), name + ".gz"
    return data, name


def send_text(title, text):
    """첨부 없이 짧은 글만 보냄(상태 알림용, 용량 한도를 거의 안 씀). 성공하면 1."""
    t = topic()
    if not t:
        return 0
    req = urllib.request.Request(f"https://ntfy.sh/{t}", data=text.encode("utf-8"), method="POST",
                                 headers={"Title": title})
    try:
        urllib.request.urlopen(req, timeout=30).read()
        return 1
    except Exception as e:
        print(f"{title}: 보내기 실패 {e}")
        return 0


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
            data, fname = _body(p, name)
            req = urllib.request.Request(f"https://ntfy.sh/{t}", data=data, method="PUT",
                                         headers={"Filename": fname, "Title": "upload"})
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


def send_file(name, title="result", path=None):
    """파일 하나를 바로 보냄(보낸 기록 없이). 성공하면 1. 압축해도 1.9MB가 넘으면 조각(이름.partKofN)으로 나눠 보냄.
    path를 주면 그 파일을 name 이름으로 보냄(못 보낸 결과 다시 보내기용)."""
    t = topic()
    p = path or os.path.join(HERE, name)
    if not t or not os.path.exists(p) or os.path.getsize(p) == 0 or os.path.getsize(p) > 60_000_000:
        return 0
    data, fname = _body(p, name)
    step = 1_900_000
    parts = [data[i:i + step] for i in range(0, len(data), step)]
    for k, part in enumerate(parts, 1):
        pname = fname if len(parts) == 1 else f"{fname}.part{k}of{len(parts)}"
        req = urllib.request.Request(f"https://ntfy.sh/{t}", data=part, method="PUT",
                                     headers={"Filename": pname, "Title": title})
        try:
            urllib.request.urlopen(req, timeout=120).read()
        except Exception as e:
            print(f"{pname}: 보내기 실패 {e}")
            try:   # 왜 실패했는지 상태 글로 남김(10-24 결과가 소리 없이 안 옴)
                send_text("status", f"{pname} 보내기 실패: {str(e)[:120]}")
            except Exception:
                pass
            return 0
        time.sleep(1)
    return 1


if __name__ == "__main__":
    k = send_pending(tuple(sys.argv[1:]) or ("play_*.jsonl",))
    print(f"보낸 파일 {k}개")
