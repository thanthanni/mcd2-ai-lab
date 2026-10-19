"""유튜브 등 플레이 영상에 IDM으로 키 입력을 채워 넣는다(VPT 3단계).

영상을 1초 10장, 160x90으로 뽑아서 녹화기와 같은 형식(session-*/meta.json, chunk-*.rgb.gz, chunk-*.csv)으로 쓴다.
키는 IDM이 낸 확률이 --threshold 넘으면 누른 걸로, 마우스는 가장 그럴듯한 칸의 가운데로 적는다.
meta.json에 "pseudo": true가 붙어서 사람 녹화와 구분된다.

    python label_videos.py --idm runs/idm/best.pt --out data_video  영상1.mp4 영상2.webm ...
    [--crop x,y,w,h]  얼굴 캠·자막 등을 빼고 게임 화면만 쓸 때(원본 픽셀 기준)
    [--start 초 --end 초]  앞뒤 인트로를 자를 때
"""
from __future__ import annotations

import argparse
import gzip
import json
import os
import subprocess
import time

import numpy as np
import torch

import hud_rules
import train

W, H, FPS, PER_CHUNK = 160, 90, 10, 600


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        return "ffmpeg"


def video_size(path):
    import re
    err = subprocess.run([ffmpeg_exe(), "-i", path], capture_output=True, text=True, errors="ignore").stderr
    m = re.search(r"Video:.*?(\d{3,5})x(\d{3,5})", err)
    return (int(m.group(1)), int(m.group(2))) if m else None


def detect_crop(path, start=None):
    """게임 화면만 남길 영역(x,y,w,h, 원본 픽셀). 못 찾으면 None.
    게임 화면은 계속 움직이고 디스코드 창(채팅 목록·참가자 칸·검은 띠)은 거의 그대로라서,
    1분 동안 많이 변한 칸들 중 가장 크게 이어진 덩어리를 게임 화면으로 본다."""
    size = video_size(path)
    if not size:
        return None
    W0, H0 = size
    gw, gh = 128, 72
    cmd = [ffmpeg_exe(), "-v", "error", "-ss", str((start or 0) + 30), "-i", path, "-t", "60",
           "-vf", f"fps=2,scale={gw}:{gh}:flags=area,format=gray", "-f", "rawvideo", "-"]
    try:
        raw = subprocess.run(cmd, capture_output=True, timeout=300).stdout
    except Exception:
        return None
    n = len(raw) // (gw * gh)
    if n < 10:
        return None
    v = np.frombuffer(raw[: n * gw * gh], np.uint8).reshape(n, gh, gw).astype(np.float32)
    std = v.std(0)
    mask = std > max(6.0, 0.25 * np.percentile(std, 95))
    # 가장 큰 덩어리(4방향 연결)
    seen = np.zeros_like(mask)
    best = None
    for y0 in range(gh):
        for x0 in range(gw):
            if not mask[y0, x0] or seen[y0, x0]:
                continue
            stack, cells = [(y0, x0)], []
            seen[y0, x0] = True
            while stack:
                y, x = stack.pop(); cells.append((y, x))
                for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                    if 0 <= yy < gh and 0 <= xx < gw and mask[yy, xx] and not seen[yy, xx]:
                        seen[yy, xx] = True; stack.append((yy, xx))
            if best is None or len(cells) > len(best):
                best = cells
    if not best or len(best) < gw * gh * 0.08:
        return None
    ys, xs = [c[0] for c in best], [c[1] for c in best]
    y1, y2, x1, x2 = min(ys), max(ys) + 1, min(xs), max(xs) + 1
    if (x2 - x1) * (y2 - y1) > gw * gh * 0.95:
        return None  # 거의 전체 화면이면 자를 필요 없음
    sx, sy = W0 / gw, H0 / gh
    x, y, w, h = int(x1 * sx), int(y1 * sy), int((x2 - x1) * sx), int((y2 - y1) * sy)
    return (x, y, w - w % 2, h - h % 2)


def frames_of(path, crop=None, start=None, end=None):
    """영상을 160x90 RGB 프레임으로 하나씩 내준다."""
    vf = []
    if crop:
        x, y, w, h = crop
        vf.append(f"crop={w}:{h}:{x}:{y}")
    vf += [f"fps={FPS}", f"scale={W}:{H}:flags=area"]
    cmd = [ffmpeg_exe(), "-v", "error"]
    if start:
        cmd += ["-ss", str(start)]
    cmd += ["-i", path]
    if end:
        cmd += ["-t", str(end - (start or 0))]
    cmd += ["-vf", ",".join(vf), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE)
    size = W * H * 3
    while True:
        b = p.stdout.read(size)
        if len(b) < size:
            break
        yield np.frombuffer(b, np.uint8).reshape(H, W, 3)
    p.wait()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--idm", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--threshold", type=float, default=0.5)
    ap.add_argument("--crop", help="x,y,w,h. 안 주면 움직이는 게임 화면을 찾아 알아서 잘라 낸다")
    ap.add_argument("--no-autocrop", action="store_true")
    ap.add_argument("--no-rules", action="store_true", help="화면 규칙(이동·물약 LT·유물2 B) 보충을 끈다")
    ap.add_argument("--start", type=float)
    ap.add_argument("--end", type=float)
    ap.add_argument("videos", nargs="+")
    a = ap.parse_args()
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    st = torch.load(a.idm, map_location=dev)
    if st.get("mode") != "idm":
        raise SystemExit("--idm에는 idm 모드로 학습한 모델을 줘.")
    keys, back, fwd, inp = st["keys"], st["back"], st["fwd"], st.get("input", "mouse")
    gx, gy = st["grid"]
    bin_names, cats = st["bin_names"], st["cats"]
    net = train.make_net(st.get("net", "small"), len(bin_names), [n for _, n in cats], st["stack"]).to(dev)
    try:
        net.load_state_dict(st["net"])
    except RuntimeError:
        raise SystemExit("이 IDM은 예전 train.py로 학습한 거라 구조가 달라. runs\\idm을 지우고 1_train_idm.bat으로 다시 학습해 줘.")
    net.eval()
    # 버튼마다 학습 끝에 맞춘 기준이 있으면 그걸 쓰고, 없으면 --threshold
    thresholds = np.array(st.get("thresholds") or [a.threshold] * len(bin_names))
    fixed = tuple(int(v) for v in a.crop.split(",")) if a.crop else None
    for vi, path in enumerate(a.videos):
        crop = fixed or (None if a.no_autocrop else detect_crop(path, a.start))
        if crop and not fixed:
            print(f"{os.path.basename(path)}: 게임 화면만 잘라 씀 (x,y,w,h)={crop}")
        name = f"session-video-{time.strftime('%Y%m%d-%H%M%S')}-{vi:02d}"
        sdir = os.path.join(a.out, name)
        os.makedirs(sdir, exist_ok=True)
        json.dump({"w": W, "h": H, "fps": FPS, "per_chunk": PER_CHUNK, "keys": keys, "format": "rgb24",
                   "pseudo": True, "input": inp, "pad_columns": True, "source": os.path.basename(path)},
                  open(os.path.join(sdir, "meta.json"), "w", encoding="utf-8"), ensure_ascii=False)
        # 1차: 화면 규칙용 신호(칸 채도, 이동 방향)만 장면마다 숫자 몇 개로 모은다
        rules = None
        if inp in ("pad", "both") and not a.no_rules:
            sats, prev, motion = [], None, []
            for f in frames_of(path, crop, a.start, a.end):
                sats.append({k: v[0] for k, v in hud_rules.slot_saturation(f[None]).items()})
                if prev is not None:
                    motion.append(hud_rules.motion_classes(np.stack([prev, f]))[0])
                prev = f
            motion.append(0)
            sat = {k: np.array([x[k] for x in sats]) for k in hud_rules.SLOTS}
            press = {}
            for k in ("potion", "a2"):   # 실측으로 확인된 것만: 물약=LT, 유물2=B (10-18 채점)
                others = np.mean([sat[o] for o in hud_rules.SLOTS if o != k], 0)
                press[k] = hud_rules.detect_presses(sat[k], others)
            rules = {"motion": np.array(motion), "lt": press["potion"], "b": press["a2"]}
        # 2차: 영상을 통째로 메모리에 올리지 않고 흘려 가며 처리한다(6시간 영상 = 10GB라 램 16GB에서 터진다)
        writer = ChunkWriter(sdir)
        ring, pending = [], []
        S = back + fwd + 1

        def flush():
            x = np.stack([w for _, w in pending])                                        # [B,S,H,W,3]
            x = torch.from_numpy(x).permute(0, 1, 4, 2, 3).reshape(len(pending), -1, H, W).to(dev)
            with torch.no_grad():
                pb, pc = net(x)
            pb = torch.sigmoid(pb).cpu().numpy()
            probs = [torch.softmax(logits, 1).cpu().numpy() for logits in pc]
            pc = [p.argmax(1) for p in probs]
            for j, (t, w) in enumerate(pending):
                on = pb[j] > thresholds
                cats = [c[j] for c in pc]
                if rules is not None and t < len(rules["motion"]):
                    # 이동: IDM이 자신 없으면(가장 높은 확률 < 0.5) 화면 흐름 규칙을 쓴다
                    if probs[0][j].max() < 0.5:
                        cats[0] = rules["motion"][t]
                    # 물약·유물2: IDM이 조금이라도(>0.2) 눌렀다고 보고 규칙도 그 근처(±1장)에서 잡았으면 누른 걸로
                    for name, idx in (("lt", 14), ("b", 11)):
                        if not on[idx] and pb[j][idx] > 0.2 and rules[name][max(0, t - 1):t + 2].any():
                            on[idx] = True
                writer.add(w[back], label_row(t, on, cats, inp, keys, gx, gy))
            pending.clear()

        for i, f in enumerate(frames_of(path, crop, a.start, a.end)):
            ring.append(f)
            if len(ring) > S:
                ring.pop(0)
            if i and i % 18000 == 0:
                print(f"  {os.path.basename(path)}: {i // 600}분 분량 처리함", flush=True)
            if len(ring) == S:
                pending.append((i - fwd, np.stack(ring)))
                if len(pending) == 256:
                    flush()
        if pending:
            flush()
        writer.close()
        if writer.total == 0:
            print("너무 짧아서 건너뜀:", path); continue
        print(f"{os.path.basename(path)}: {writer.total}장에 입력을 채움 → {sdir}", flush=True)


def label_row(t, on, cats, inp, keys, gx, gy):
    if inp in ("pad", "both"):
        btn = sum(bit for (_, bit), o in zip(train.PAD_BITS, on[:14]) if o)
        lx, ly = train.stick_value(int(cats[0])); rx, ry = train.stick_value(int(cats[1]))
        mx = my = 0.5; bits = 0
        if inp == "both":
            cell = int(cats[2]); mx, my = (cell % gx + 0.5) / gx, (cell // gx + 0.5) / gy
            bits = sum(1 << b for b in range(len(keys)) if on[16 + b])
        return (t, mx, my, bits, btn, lx, ly, rx, ry, 255 * int(on[14]), 255 * int(on[15]))
    cell = int(cats[0])
    bits = sum(1 << b for b in range(len(keys)) if on[b])
    return (t, (cell % gx + 0.5) / gx, (cell // gx + 0.5) / gy, bits, 0, 0, 0, 0, 0, 0, 0)


class ChunkWriter:
    """녹화기와 같은 조각 파일(600장씩)로 쓴다."""
    def __init__(self, sdir):
        self.sdir, self.frames, self.rows, self.n, self.total = sdir, [], [], 0, 0

    def add(self, frame, row):
        self.frames.append(frame); self.rows.append(row)
        if len(self.rows) == PER_CHUNK:
            self.write()

    def write(self):
        if not self.rows:
            return
        self.n += 1
        base = os.path.join(self.sdir, f"chunk-{self.n:04d}")
        with gzip.open(base + ".rgb.gz", "wb", compresslevel=1) as f:
            f.write(np.stack(self.frames).tobytes())
        with open(base + ".csv", "w") as f:
            f.write("t_ms,mx,my,keys,pad_buttons,lx,ly,rx,ry,lt,rt\n")
            f.write("".join(f"{r[0] * 100},{r[1]:.4f},{r[2]:.4f}," + ",".join(str(int(v)) for v in r[3:]) + "\n" for r in self.rows))
        self.total += len(self.rows)
        self.frames, self.rows = [], []

    def close(self):
        self.write()

if __name__ == "__main__":
    main()
