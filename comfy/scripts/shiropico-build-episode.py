"""Build a full SHIRO & PICO episode (motion comic) from a shotlist JSON.

Per beat: VOICEVOX voice (シロ=四国めたん2 girl / ピコ=ずんだもん3 boy / narration) +
on-model 立ち絵 (emotions/{shiro,pico}, シロ flipped to face inward) over a scene bg
(Ken Burns) + caption + BGM/SFX + breathing/talk-pop + flash/shake FX. Concatenates
all beats and PREPENDS the cinematic OP. Needs VOICEVOX at localhost:50021
(kubectl port-forward) for synthesis.

Out: resources/episode/sp-ep01-full.mp4
"""
from __future__ import annotations
import hashlib, json, math, os, subprocess, tempfile, wave
from pathlib import Path
import numpy as np
import httpx
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2] / "data/ghosthacker-shiropico"
BG = ROOT / "resources/bg2"
EMO = ROOT / "character-refs/emotions"
OP = ROOT / "resources/opening/sp-opening-v2.mp4"
SHOTLIST = ROOT / "episode-01-shotlist.json"
OUT = ROOT / "resources/episode"; OUT.mkdir(parents=True, exist_ok=True)
VCACHE = Path("/tmp/sp-vcache"); VCACHE.mkdir(exist_ok=True)
VV = "http://localhost:50021"
FONT = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
if not os.path.exists(FONT): FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
W, H, FPS, SR = 1080, 1920, 30, 44100
SPK = {"shiro": 2, "pico": 3, "narration": 2}  # voicevox speaker ids


def voicevox(text, speaker):
    key = hashlib.md5(f"{speaker}:{text}".encode()).hexdigest()[:16]
    cached = VCACHE / f"{key}.wav"
    if cached.exists(): return cached
    try:
        q = httpx.post(f"{VV}/audio_query", params={"text": text, "speaker": speaker}, timeout=30).json()
        q["speedScale"] = 0.97
        w = httpx.post(f"{VV}/synthesis", params={"speaker": speaker}, json=q,
                       headers={"accept": "audio/wav"}, timeout=30)
        if w.status_code == 200 and w.content:
            cached.write_bytes(w.content); return cached
    except Exception as exc:
        print("  voicevox err:", str(exc)[:80])
    return None


def _wav(p):
    with wave.open(str(p), "rb") as w:
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0; sr = w.getframerate()
        if w.getnchannels() == 2: a = a.reshape(-1, 2).mean(1)
    if sr != SR: a = np.interp(np.linspace(0, len(a), int(len(a) * SR / sr)), np.arange(len(a)), a)
    return a

def _bgm(dur, mood=0):
    t = np.arange(int(dur * SR)) / SR
    chord = [[220, 277, 330], [196, 247, 294], [165, 220, 262]][mood % 3]
    sig = sum(np.sin(2 * np.pi * f * t) * (0.5 ** i) for i, f in enumerate(chord))
    return (sig * (0.5 + 0.3 * np.sin(2 * np.pi * 0.2 * t)) / 7).astype(np.float32)

def _sfx(kind, dur):
    n = int(dur * SR); t = np.arange(n) / SR
    if kind == "pop": return (np.sin(2 * np.pi * 660 * t) * np.exp(-t * 18) * 0.5).astype(np.float32)
    if kind == "whoosh": return (np.random.randn(n) * np.exp(-((t - 0.15) ** 2) / 0.01) * 0.4).astype(np.float32)
    if kind == "alarm": return ((np.sin(2 * np.pi * 880 * t) * (np.sin(2 * np.pi * 6 * t) > 0)) * np.exp(-t * 1.2) * 0.4).astype(np.float32)
    if kind == "chime": return ((np.sin(2 * np.pi * 1320 * t) + 0.5 * np.sin(2 * np.pi * 1980 * t)) * np.exp(-t * 3) * 0.4).astype(np.float32)
    if kind == "ghost": return (np.sin(2 * np.pi * (300 + 200 * np.sin(2 * np.pi * 1.5 * t)) * t) * np.exp(-t * 1.5) * 0.35).astype(np.float32)
    if kind == "ambient": return (np.random.randn(n) * 0.05 * (0.5 + 0.5 * np.sin(2 * np.pi * 0.5 * t))).astype(np.float32)
    return np.zeros(n, np.float32)

def _cover(img, w, h):
    iw, ih = img.size; s = max(w / iw, h / ih)
    img = img.resize((max(1, int(iw * s)), max(1, int(ih * s))), Image.Resampling.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))

def _emo(side, name):
    p = EMO / side / f"{name}.png"
    return Image.open(p if p.exists() else EMO / side / "normal.png").convert("RGBA")

def _caption(text):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    try: font = ImageFont.truetype(FONT, 48)
    except Exception: font = ImageFont.load_default()
    # wrap to ~22 chars
    lines, cur = [], ""
    for ch in text:
        if len(cur) >= 22 and ch in "、。！？ 　":
            lines.append(cur + (ch if ch.strip() else "")); cur = ""
        else: cur += ch
    if cur: lines.append(cur)
    lines = lines[:3]
    bar = Image.new("RGBA", (W, 300), (0, 0, 0, 0)); bd = ImageDraw.Draw(bar)
    for yy in range(300): bd.line([(0, yy), (W, yy)], fill=(8, 16, 22, int(195 * yy / 300)))
    img.alpha_composite(bar, (0, H - 300))
    y = H - 250
    for ln in lines:
        bb = d.textbbox((0, 0), ln, font=font); x = (W - (bb[2] - bb[0])) // 2
        d.text((x, y), ln, font=font, fill=(255, 255, 255, 255), stroke_width=6, stroke_fill=(8, 16, 22, 235)); y += 80
    return img


def build():
    beats = json.loads(SHOTLIST.read_text())
    tmp = Path(tempfile.mkdtemp())
    ch_h = int(H * 0.26); eo = int(ch_h * 0.06)
    bgcache = {}
    seg_v, seg_a = [], []
    for bi, b in enumerate(beats):
        text = (b.get("text") or "").strip()
        spk = b.get("speaker", "none")
        voice = None
        if b.get("voice") and spk in SPK and text:
            wavp = voicevox(text, SPK[spk])
            if wavp: voice = _wav(wavp)
        dur = max(2.4, (len(voice) / SR + 0.9) if voice is not None else 2.8)
        nf = int(dur * FPS)
        bgkey = b.get("bg", "bg-dubai-night")
        if bgkey not in bgcache:
            f = BG / f"{bgkey}.png"
            if not f.exists(): f = BG / "bg-dubai-night.png"
            bgcache[bgkey] = _cover(Image.open(f).convert("RGB"), int(W * 1.12), int(H * 1.12))
        bgimg = bgcache[bgkey]
        sh = _emo("shiro", b.get("shiro_emo", "normal")); pi = _emo("pico", b.get("pico_emo", "normal"))
        def fit(im): s = ch_h / im.height; return im.resize((int(im.width * s), ch_h), Image.Resampling.LANCZOS)
        sh, pi = fit(sh), fit(pi)
        cap = _caption(text if text else "")
        fx = b.get("fx"); sfx = b.get("sfx")
        fdir = tmp / f"b{bi:03d}"; fdir.mkdir()
        for f in range(nf):
            tt = f / FPS
            z = 1.0 + 0.05 * (f / max(1, nf))
            cw, chh = int(W / z), int(H / z)
            shake = int(7 * math.sin(tt * 40)) if fx == "shake" else 0
            x0 = (bgimg.width - cw) // 2 + shake; y0 = (bgimg.height - chh) // 2
            fr = bgimg.crop((x0, y0, x0 + cw, y0 + chh)).resize((W, H), Image.Resampling.LANCZOS).convert("RGBA")
            fr.alpha_composite(Image.new("RGBA", (W, H), (8, 14, 22, 95)))
            def place(img, side):
                bob = int(7 * math.sin(tt * 3.2 + (0 if side == "shiro" else 1.5)))
                im = img
                if spk == side and voice is not None:
                    sc = 1.0 + 0.03 * abs(math.sin(tt * 13)); im = img.resize((int(img.width * sc), int(img.height * sc)), Image.Resampling.LANCZOS)
                if side == "shiro":
                    im = im.transpose(Image.Transpose.FLIP_LEFT_RIGHT); x = -eo
                else:
                    x = W - im.width + eo
                fr.alpha_composite(im, (x, H - im.height - 240 + bob))
            place(sh, "shiro"); place(pi, "pico")
            fr.alpha_composite(cap)
            if fx == "flash" and tt < 0.4:
                fr.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, int(150 * (1 - tt / 0.4)))))
            fr.convert("RGB").save(fdir / f"{f:04d}.png")
        seg = tmp / f"s{bi:03d}.mp4"
        subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(fdir / "%04d.png"),
                        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(seg)], capture_output=True, check=True)
        seg_v.append(seg)
        bed = _bgm(dur, bi)
        if sfx and sfx != "null":
            s = _sfx(sfx, min(dur, 1.2)); bed[:len(s)] += s
        if voice is not None:
            lead = int(0.4 * SR); end = min(len(bed), lead + len(voice)); bed[lead:end] += voice[:end - lead]
        ap = tmp / f"a{bi:03d}.wav"
        with wave.open(str(ap), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((np.clip(bed, -1, 1) * 32767).astype(np.int16).tobytes())
        seg_a.append(ap)
        if bi % 8 == 0: print(f"  beat {bi}/{len(beats)}", flush=True)
    # body video + audio
    lv = tmp / "v.txt"; lv.write_text("".join(f"file '{p}'\n" for p in seg_v))
    body_v = tmp / "bodyv.mp4"; subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lv), "-c", "copy", str(body_v)], capture_output=True, check=True)
    la = tmp / "a.txt"; la.write_text("".join(f"file '{p}'\n" for p in seg_a))
    body_a = tmp / "bodya.wav"; subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(la), "-c", "copy", str(body_a)], capture_output=True, check=True)
    body = tmp / "body.mp4"
    subprocess.run(["ffmpeg", "-y", "-i", str(body_v), "-i", str(body_a), "-c:v", "libx264", "-preset", "medium", "-crf", "20",
                    "-c:a", "aac", "-b:a", "160k", "-pix_fmt", "yuv420p", "-shortest", str(body)], capture_output=True, check=True)
    # prepend OP (re-encode both to identical params, concat)
    out = OUT / "sp-ep01-full.mp4"
    parts = [OP, body] if OP.exists() else [body]
    norm = []
    for i, p in enumerate(parts):
        np_out = tmp / f"n{i}.mp4"
        subprocess.run(["ffmpeg", "-y", "-i", str(p), "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={FPS}",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k", "-ar", str(SR), "-pix_fmt", "yuv420p", str(np_out)], capture_output=True, check=True)
        norm.append(np_out)
    lf = tmp / "final.txt"; lf.write_text("".join(f"file '{p}'\n" for p in norm))
    r = subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lf), "-c", "copy", str(out)], capture_output=True, text=True)
    if r.returncode != 0:
        print("final concat fail:\n", r.stderr[-700:]); return
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
    print(f"DONE → {out} ({out.stat().st_size // 1024} KB, {dur}s)")


if __name__ == "__main__":
    build()
