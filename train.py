"""마던2 AI 학습 (VPT를 작게 따라 하기).

--mode bc  : 모방학습. 지난 화면 4장을 보고 다음 순간의 입력을 맞힌다.
--mode idm : 키 맞히는 AI(역동역학 모델). 앞뒤 화면 5장(t-2..t+2)을 보고 t의 입력을 맞힌다.
             이걸로 영상에 입력을 채워 넣는다(label_videos.py).
--input    : mouse(키보드+마우스: 13키 + 마우스 16x9칸) / pad(패드: 버튼 16개 + 왼·오른 스틱 9방향)
             / both(패드로 하다가 가끔 마우스: 둘 다) / auto(데이터 보고 정함)
PC(RTX)와 구글 코랩 둘 다에서 돈다. 중간 결과를 --out 폴더에 자주 저장하고, 다시 켜면 이어서 학습한다.

    python train.py --mode idm --data <녹화 data 폴더> --out runs/idm
    python train.py --mode bc  --data <녹화 data 폴더> --data <영상 라벨 폴더> --out runs/bc
"""
from __future__ import annotations

import argparse
import glob
import gzip
import json
import math
import os
import time

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F

GX, GY = 16, 9     # 마우스 위치를 나누는 칸
# 모드마다: 과거 몇 장, 미래 몇 장, 정답을 몇 장 뒤 입력에서 가져올지
# bc는 화면을 보고 나서 누른 입력(=다음 프레임에 기록된 입력)을 맞힌다. idm은 t에 기록된 입력을 앞뒤를 보고 맞힌다.
MODES = {"bc": (3, 0, 1), "idm": (2, 2, 0)}
BACK, FWD, SHIFT = MODES["bc"]
STACK = BACK + FWD + 1

# 입력 열(acts): mx, my, keys, pad_buttons, lx, ly, rx, ry, lt, rt
NCOL = 10
# 패드 버튼: XInput 비트 14개 + 트리거 2개(눌림 = 30/255 넘음)
PAD_BITS = [("up", 0x1), ("down", 0x2), ("left", 0x4), ("right", 0x8), ("start", 0x10), ("back", 0x20),
            ("ls", 0x40), ("rs", 0x80), ("lb", 0x100), ("rb", 0x200), ("a", 0x1000), ("b", 0x2000), ("x", 0x4000), ("y", 0x8000)]
PAD_NAMES = [n for n, _ in PAD_BITS] + ["lt", "rt"]
STICK_DEAD = 0.3   # 스틱을 이만큼 넘게 기울여야 방향으로 친다


def set_mode(mode: str):
    global BACK, FWD, SHIFT, STACK
    BACK, FWD, SHIFT = MODES[mode]
    STACK = BACK + FWD + 1


def stick_class(x: float, y: float) -> int:
    """스틱 값(-32768..32767)을 0=가만히, 1..8=오른쪽부터 반시계 45도씩으로."""
    fx, fy = x / 32767.0, y / 32767.0
    if math.hypot(fx, fy) < STICK_DEAD:
        return 0
    return 1 + int(round(math.atan2(fy, fx) / (math.pi / 4))) % 8


def stick_value(c: int) -> tuple[int, int]:
    """stick_class의 반대: 방향 → 스틱 값(끝까지 기울인 것으로)."""
    if c == 0:
        return 0, 0
    ang = (c - 1) * math.pi / 4
    return int(32767 * math.cos(ang)), int(32767 * math.sin(ang))


def heads_for(inp: str, nkeys: int):
    """(켜고 끄는 입력 이름들, 여러 개 중 하나 고르는 입력들[(이름, 가짓수)])"""
    if inp == "pad":
        return PAD_NAMES, [("lstick", 9), ("rstick", 9)]
    if inp == "both":
        return None, [("lstick", 9), ("rstick", 9), ("mouse", GX * GY)]  # 이름은 패드 + 녹화의 keys
    return None, [("mouse", GX * GY)]  # 이름은 녹화의 keys를 쓴다


def targets(row, inp: str, nkeys: int):
    mx, my, k, pb, lx, ly, rx, ry, lt, rt = row
    pad_b = [float(int(pb) & bit != 0) for _, bit in PAD_BITS] + [float(lt > 30), float(rt > 30)]
    sticks = [stick_class(lx, ly), stick_class(rx, ry)]
    key_b = [float((int(k) >> i) & 1) for i in range(nkeys)]
    cell = min(int(my * GY), GY - 1) * GX + min(int(mx * GX), GX - 1)
    if inp == "pad":
        return pad_b, sticks
    if inp == "both":
        return pad_b + key_b, sticks + [cell]
    return key_b, [cell]


def load_sessions(data_dirs, cache_dir: str):
    """녹화 세션을 읽어 (프레임 uint8 [N,H,W,3], 입력 [N,10]) 목록으로. 압축 푼 결과는 cache_dir에 .npy로 남겨 다음엔 바로 읽는다."""
    os.makedirs(cache_dir, exist_ok=True)
    out = []
    keys = None
    if isinstance(data_dirs, str):
        data_dirs = [data_dirs]
    sdirs = [d for root in data_dirs for d in sorted(glob.glob(os.path.join(root, "session-*")))]
    for sdir in sdirs:
        meta = json.load(open(os.path.join(sdir, "meta.json"), encoding="utf-8"))
        keys = keys or meta["keys"]
        name = os.path.basename(os.path.dirname(sdir.rstrip("/\\"))) + "_" + os.path.basename(sdir)
        fpath, apath = os.path.join(cache_dir, name + ".frames.npy"), os.path.join(cache_dir, name + ".act2.npy")
        if not (os.path.exists(fpath) and os.path.exists(apath)):
            frames, acts = [], []
            for g in sorted(glob.glob(os.path.join(sdir, "chunk-*.rgb.gz"))):
                try:
                    raw = gzip.open(g).read()
                except (EOFError, OSError):  # 녹화기를 갑자기 닫아 끝이 잘린 조각
                    continue
                fsz = meta["h"] * meta["w"] * 3
                f = np.frombuffer(raw[: len(raw) // fsz * fsz], np.uint8).reshape(-1, meta["h"], meta["w"], 3)
                a = np.loadtxt(g.replace(".rgb.gz", ".csv"), delimiter=",", skiprows=1, ndmin=2)
                n = min(len(f), len(a))
                act = np.zeros((n, NCOL), np.float32)
                cols = min(NCOL, a.shape[1] - 1)          # 옛 녹화(패드 열 없음)는 0으로 채운다
                act[:, :cols] = a[:n, 1:1 + cols]
                frames.append(f[:n]); acts.append(act)
            if not frames:
                continue
            np.save(fpath, np.concatenate(frames)); np.save(apath, np.concatenate(acts))
        out.append((np.load(fpath, mmap_mode="r"), np.load(apath), fpath))
    return out, keys or []


def guess_input(sessions) -> str:
    """패드를 만진 장면이 5% 넘으면 패드, 거기에 마우스 클릭도 1% 넘으면 둘 다로 본다."""
    acts = np.concatenate([s[1] for s in sessions])
    padded = (acts[:, 3] != 0) | (np.hypot(acts[:, 4], acts[:, 5]) > 32767 * STICK_DEAD)
    clicked = (acts[:, 2].astype(np.int64) & 0b11) != 0   # lmb, rmb
    if padded.mean() > 0.05:
        return "both" if clicked.mean() > 0.01 else "pad"
    return "mouse"


class Clips(torch.utils.data.Dataset):
    def __init__(self, sessions, nkeys, idx, inp, augment=False):
        # 윈도우의 데이터 로더 일꾼은 새 프로세스라 전역 모드를 모른다 → 여기 담아 간다.
        # 화면 배열(수 GB)은 넘기지 않고 파일 경로만 넘겨서 일꾼이 각자 연다(통째로 넘기면 윈도우에서 Errno 22로 죽었다, 10-18).
        self.paths = [s[2] for s in sessions]
        self.acts = [s[1] for s in sessions]
        self.frames = None
        self.nkeys, self.idx, self.inp, self.augment = nkeys, idx, inp, augment
        self.back, self.fwd, self.shift = BACK, FWD, SHIFT

    def __getstate__(self):
        st = dict(self.__dict__)
        st["frames"] = None
        return st

    def __len__(self):
        return len(self.idx)

    def __getitem__(self, i):
        si, t = self.idx[i]
        if self.frames is None:
            self.frames = [np.load(p, mmap_mode="r") for p in self.paths]
        frames, acts = self.frames[si], self.acts[si]
        x = np.array(frames[t - self.back : t + self.fwd + 1])      # [STACK,H,W,3] (복사: mmap은 쓰기 불가)
        if self.augment:
            x = augment_frames(x)
        x = torch.from_numpy(x).permute(0, 3, 1, 2).reshape(-1, x.shape[1], x.shape[2])
        b, c = targets(acts[t + self.shift], self.inp, self.nkeys)
        return x, torch.tensor(b), torch.tensor(c, dtype=torch.long)


def augment_frames(x):
    """외우기 방지: 같은 장면도 매번 조금 다르게 보이게 한다(밝기·대비·색감, 몇 픽셀 밀기). 겹친 화면 전체에 같은 변화를 준다.
    좌우 뒤집기는 스틱 방향 정답까지 바꿔야 해서 안 한다."""
    rng = np.random.default_rng()
    f = x.astype(np.float32)
    f = (f - 128) * rng.uniform(0.8, 1.2) + 128 + rng.uniform(-20, 20)     # 대비, 밝기
    f *= rng.uniform(0.92, 1.08, size=3)                                      # 색감
    dy, dx = rng.integers(-4, 5), rng.integers(-6, 7)
    f = np.roll(f, (dy, dx), axis=(1, 2))
    return np.clip(f, 0, 255).astype(np.uint8)


def make_index(sessions, valid_every=10):
    """1분(600장)씩 묶어 10묶음 중 1묶음은 검증용으로 뗀다(바로 옆 장면끼리 섞이면 점수가 부풀려져서)."""
    train, valid = [], []
    for si, (frames, acts, _) in enumerate(sessions):
        for t in range(BACK, len(acts) - max(SHIFT, FWD)):
            (valid if (t // 600) % valid_every == valid_every - 1 else train).append((si, t))
    return train, valid


class Net(nn.Module):
    def __init__(self, nbin, cats, stack=None):
        super().__init__()
        c = 3 * (stack or STACK)
        # GroupNorm: 정규화가 없으면 처음 몇 바퀴를 제자리에서 맴돌았다(가짜 게임 시험, 10-18)
        self.body = nn.Sequential(
            nn.Conv2d(c, 32, 5, 2, 2), nn.GroupNorm(8, 32), nn.ReLU(),
            nn.Conv2d(32, 64, 3, 2, 1), nn.GroupNorm(8, 64), nn.ReLU(),
            nn.Conv2d(64, 64, 3, 2, 1), nn.GroupNorm(8, 64), nn.ReLU(),
            nn.Conv2d(64, 128, 3, 2, 1), nn.GroupNorm(8, 128), nn.ReLU(),
            nn.AdaptiveAvgPool2d((3, 5)), nn.Flatten(),
            nn.Dropout(0.3),                      # 외우기 방지: 학습 때 일부를 무작위로 끈다
            nn.Linear(128 * 15, 256), nn.ReLU(),
            nn.Dropout(0.3),
        )
        self.bin = nn.Linear(256, nbin)
        self.cats = nn.ModuleList(nn.Linear(256, n) for n in cats)

    def forward(self, x):
        h = self.body(x.float() / 255.0)
        return self.bin(h), [head(h) for head in self.cats]


class PretrainedNet(nn.Module):
    """미리 학습된 ResNet18(ImageNet)을 눈으로 쓴다. 화면마다 같은 눈으로 특징을 뽑아 이어 붙이고 뒤쪽 판단만 새로 배운다.
    데이터가 적을 때(수십 분~몇 시간) 처음부터 배우는 Net보다 잘 배우는 경우가 많다."""
    def __init__(self, nbin, cats, stack=None, freeze=True):
        super().__init__()
        import torchvision
        self.stack = stack or STACK
        m = torchvision.models.resnet18(weights=torchvision.models.ResNet18_Weights.IMAGENET1K_V1)
        self.eye = nn.Sequential(*list(m.children())[:-1])   # 끝의 분류층만 빼고, 출력 512
        self.freeze = freeze
        if freeze:
            for p in self.eye.parameters():
                p.requires_grad = False
        self.register_buffer("mean", torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1))
        self.register_buffer("std", torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1))
        self.mix = nn.Sequential(nn.Dropout(0.3), nn.Linear(512 * self.stack, 256), nn.ReLU(), nn.Dropout(0.3))
        self.bin = nn.Linear(256, nbin)
        self.cats = nn.ModuleList(nn.Linear(256, n) for n in cats)

    def train(self, mode=True):
        super().train(mode)
        if self.freeze:
            self.eye.eval()   # 얼린 눈은 배치 정규화 통계도 그대로 둔다
        return self

    def forward(self, x):
        b, c, h, w = x.shape
        f = x.float().view(b * self.stack, 3, h, w) / 255.0
        f = (f - self.mean) / self.std
        f = nn.functional.interpolate(f, scale_factor=2, mode="bilinear", align_corners=False)  # 160x90 → 320x180
        with torch.set_grad_enabled(not self.freeze and self.training):
            z = self.eye(f).flatten(1)
        h = self.mix(z.view(b, -1))
        return self.bin(h), [head(h) for head in self.cats]


def make_net(kind, nbin, cats, stack=None):
    return PretrainedNet(nbin, cats, stack) if kind == "resnet18" else Net(nbin, cats, stack)


def cat_hit(name, pred, true):
    if name == "mouse":  # 정답 칸 근처(±1칸)
        return ((pred % GX - true % GX).abs().le(1) & (pred // GX - true // GX).abs().le(1)).float().mean()
    return (pred == true).float().mean()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--mode", choices=list(MODES), default="bc")
    ap.add_argument("--input", choices=["auto", "mouse", "pad", "both"], default="auto")
    ap.add_argument("--data", required=True, action="append", help="녹화 data 폴더(여러 번 줄 수 있음)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--save-every", type=int, default=600, help="몇 초마다 중간 저장할지(코랩 끊김 대비)")
    ap.add_argument("--workers", type=int, default=2)
    ap.add_argument("--no-augment", action="store_true", help="외우기 방지용 화면 변형을 끈다")
    ap.add_argument("--net", choices=["small", "resnet18"], default="small", help="resnet18: 미리 학습된 이미지 모델을 눈으로 쓴다")
    a = ap.parse_args()

    set_mode(a.mode)
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    print("장치:", dev, torch.cuda.get_device_name(0) if dev == "cuda" else "")
    sessions, keys = load_sessions(a.data, os.path.join(a.out, "cache"))
    if not sessions:
        raise SystemExit("녹화 데이터가 없어: " + ", ".join(a.data))
    inp = guess_input(sessions) if a.input == "auto" else a.input
    tr, va = make_index(sessions)
    nk = len(keys)
    bin_names, cats = heads_for(inp, nk)
    bin_names = bin_names or ((PAD_NAMES + keys) if inp == "both" else keys)
    print(f"입력 {dict(pad='패드', both='패드+마우스', mouse='키보드+마우스')[inp]}, 세션 {len(sessions)}개, 학습 {len(tr)}장, 검증 {len(va)}장")

    # 드물게 누르는 버튼(물약·유물 등)도 배우게 가중치를 준다
    sample = [targets(r, inp, nk)[0] for s in sessions for r in s[1][:: max(1, len(s[1]) // 20000)]]
    pos = np.array(sample).mean(0)
    pos_w = torch.tensor(np.clip((1 - pos) / np.maximum(pos, 1e-3), 1, 10), dtype=torch.float32, device=dev)  # 상한 50이면 드문 버튼(물약)을 아무 데서나 눌렀다고 했다(10-18)

    net = make_net(a.net, len(bin_names), [n for _, n in cats]).to(dev)
    opt = torch.optim.AdamW([p for p in net.parameters() if p.requires_grad], lr=1e-3, weight_decay=5e-4)
    scaler = torch.amp.GradScaler(enabled=dev == "cuda")
    os.makedirs(a.out, exist_ok=True)
    ck = os.path.join(a.out, "last.pt")
    epoch, step = 0, 0
    if os.path.exists(ck):
        st = torch.load(ck, map_location=dev)
        if st.get("mode", "bc") != a.mode or st.get("input", "mouse") != inp or st.get("net", "small") != a.net:
            raise SystemExit(f"{ck}는 다른 종류({st.get('mode')}, {st.get('input')}) 모델이야. --out을 다른 폴더로 줘.")
        net.load_state_dict(st["net"]); opt.load_state_dict(st["opt"]); epoch, step = st["epoch"], st["step"]
        print(f"이어서 학습: {epoch}번째 바퀴부터")

    def save(path, ep):
        tmp = path + ".tmp"
        torch.save({"net": net.state_dict(), "opt": opt.state_dict(), "epoch": ep, "step": step, "keys": keys,
                    "input": inp, "bin_names": bin_names, "cats": cats, "net": a.net,
                    "mode": a.mode, "back": BACK, "fwd": FWD, "stack": STACK, "grid": [GX, GY], "shift": SHIFT}, tmp)
        os.replace(tmp, path)

    def losses(pb, pc, b, c):
        loss = F.binary_cross_entropy_with_logits(pb.float(), b, pos_weight=pos_w)
        for j, logits in enumerate(pc):
            loss = loss + F.cross_entropy(logits.float(), c[:, j])
        return loss

    mk = lambda idx, sh: torch.utils.data.DataLoader(Clips(sessions, nk, idx, inp, augment=sh and not a.no_augment), batch_size=a.batch, shuffle=sh,
                                                     num_workers=a.workers, pin_memory=dev == "cuda", drop_last=sh)
    tl, vl = mk(tr, True), mk(va or tr[:1000], False)
    best = float("inf")
    last_save = time.time()
    while epoch < a.epochs:
        net.train(); t0 = time.time(); tot = 0.0
        for x, b, c in tl:
            x, b, c = x.to(dev, non_blocking=True), b.to(dev), c.to(dev)
            with torch.autocast(dev, enabled=dev == "cuda"):
                pb, pc = net(x)
                loss = losses(pb, pc, b, c)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward(); scaler.step(opt); scaler.update()
            tot += loss.item(); step += 1
            if time.time() - last_save > a.save_every:
                save(ck, epoch); last_save = time.time()
        # 검증: 버튼은 맞힌 비율, 마우스는 정답 칸 ±1칸, 스틱은 방향이 맞은 비율
        net.eval(); vloss = 0.0; bacc = []; cacc = [[] for _ in cats]
        with torch.no_grad():
            for x, b, c in vl:
                x, b, c = x.to(dev), b.to(dev), c.to(dev)
                pb, pc = net(x)
                vloss += losses(pb, pc, b, c).item() * len(x)
                bacc.append(((pb > 0).float() == b).float().mean(0).cpu())
                for j, logits in enumerate(pc):
                    cacc[j].append(cat_hit(cats[j][0], logits.argmax(1), c[:, j]).cpu())
        vloss /= max(1, len(vl.dataset))
        ba = torch.stack(bacc).mean(0)
        epoch += 1
        print(f"[{epoch}/{a.epochs}] 학습 {tot / max(1, len(tl)):.3f} 검증 {vloss:.3f} "
              + " ".join(f"{n} {torch.stack(v).mean():.0%}" for (n, _), v in zip(cats, cacc))
              + " | 버튼 " + " ".join(f"{n}:{v:.0%}" for n, v in zip(bin_names, ba.tolist())) + f" ({time.time() - t0:.0f}초)", flush=True)
        save(ck, epoch); last_save = time.time()
        if vloss < best:
            best = vloss; save(os.path.join(a.out, "best.pt"), epoch)
    calibrate(os.path.join(a.out, "best.pt"), net, vl, bin_names, dev)
    print("끝. 쓸 모델:", os.path.join(a.out, "best.pt"))


def calibrate(path, net, loader, names, dev):
    """버튼마다 '몇 % 넘으면 눌렀다고 볼지'를 검증 구간에서 F1이 가장 높게 맞춰 best.pt에 같이 저장한다."""
    st = torch.load(path, map_location=dev)
    net.load_state_dict(st["net"]); net.eval()
    P, Y = [], []
    with torch.no_grad():
        for x, b, _ in loader:
            pb, _ = net(x.to(dev))
            P.append(torch.sigmoid(pb).cpu()); Y.append(b)
    P, Y = torch.cat(P).numpy(), torch.cat(Y).numpy() > 0.5
    th = []
    print("버튼 기준 맞추기(검증 구간):")
    for i, n in enumerate(names):
        best_t, best_f = 0.5, -1.0
        if Y[:, i].sum() >= 3:
            for t in np.arange(0.3, 0.99, 0.02):
                pr = P[:, i] > t
                tp = (pr & Y[:, i]).sum(); fp = (pr & ~Y[:, i]).sum(); fn = (~pr & Y[:, i]).sum()
                f = 2 * tp / max(1, 2 * tp + fp + fn)
                if f > best_f:
                    best_t, best_f = float(t), float(f)
            print(f"  {n}: 기준 {best_t:.2f}, F1 {best_f:.2f} (누른 장면 {int(Y[:, i].sum())})")
        else:
            best_t = 0.9  # 검증 구간에 거의 안 눌렀으면 보수적으로
        th.append(best_t)
    st["thresholds"] = th
    torch.save(st, path + ".tmp"); os.replace(path + ".tmp", path)


if __name__ == "__main__":
    main()
