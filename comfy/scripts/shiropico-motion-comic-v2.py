"""SHIRO & PICO ep01 motion comic v2 — faithful characters + VOICEVOX + SFX/BGM + FX.

Fixes v1's three problems:
  1. characters drifted (SDXL text2img) → composite the REAL 立ち絵 (emotions/{shiro,pico})
     directly, so シロ/ピコ are 100% on-model.
  2. no audio → VOICEVOX dialogue (シロ=四国めたん2 / ピコ=ずんだもん3) + synth BGM + SFX.
  3. no FX → Ken Burns bg + per-character breathing bob + speaker talk-pop + action flash/shake.

Inputs (prepared by the caller):
  - resources/bg2/*.png                      character-free cyber backgrounds (comfyui)
  - character-refs/emotions/{shiro,pico}/*.png   the canonical cast (transparent bust)
  - /tmp/sp-voices/*.wav                     VOICEVOX dialogue (pre-synthesized)
Out: resources/motion-comic/sp-ep01-motion-comic-v2.mp4
"""
from __future__ import annotations
import math, os, subprocess, tempfile, wave
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2] / "data/ghosthacker-shiropico"
BG = ROOT / "resources/bg2"
EMO = ROOT / "character-refs/emotions"
VOICE = Path("/tmp/sp-voices")
OUT = ROOT / "resources/motion-comic"; OUT.mkdir(parents=True, exist_ok=True)
FONT = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
if not os.path.exists(FONT):
    FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
W, H, FPS, SR = 1080, 1920, 30, 44100

# beat = (bg, shiro_emo, pico_emo, speaker, voice_wav|None, [caption lines], sfx, fx)
BEATS = [
    ("bg-dubai-night", "normal", "normal", None, None,
     ["ドバイの夜。街じゅうの車が", "いっせいに眠りはじめた——"], "ambient", None),
    ("bg-dubai-night", "normal", "happy", "pico", "pico_1",
     ["ピコ「うっわ、街ぜんぶ", "　　お寝坊じゃん！ウケる」"], "pop", None),
    ("bg-dubai-night", "normal", "normal", "shiro", "shiro_1",
     ["シロ「……笑えないよ。みんな", "　　操られて眠ってる。起こさないと」"], None, None),
    ("bg-street", "normal", "smug", "pico", "pico_2",
     ["ピコ「こんなの楽勝〜。", "　　オレ天才ハッカーだし？」"], "whoosh", "flash"),
    ("bg-street", "normal", "panic", "pico", "pico_3",
     ["ピコ「えっ、なんで増えんの!?", "　　どわー間に合わなーっ！」"], "alarm", "shake"),
    ("bg-street", "normal", "surprised", "shiro", "shiro_2",
     ["シロ「——スリープ・コール。", "　　隔離して、正気に戻す。これがEDR」"], "chime", "flash"),
    ("bg-skyscraper-ghost", "normal", "surprised", "shiro", "shiro_3",
     ["シロ「情報は物理だ。", "　　これは——Ghostだ」"], "ghost", None),
]


# ── audio synthesis (numpy) ──────────────────────────────────────────────────
def _wav_read(p):
    with wave.open(str(p), "rb") as w:
        n, sr = w.getnframes(), w.getframerate()
        a = np.frombuffer(w.readframes(n), dtype=np.int16).astype(np.float32) / 32768.0
        if w.getnchannels() == 2:
            a = a.reshape(-1, 2).mean(axis=1)
    if sr != SR:
        a = np.interp(np.linspace(0, len(a), int(len(a) * SR / sr)), np.arange(len(a)), a)
    return a

def _bgm(dur):
    t = np.arange(int(dur * SR)) / SR
    # slow cyber pad: stacked detuned sines + soft pulse
    chord = [220, 277, 330, 440]
    sig = sum(np.sin(2 * np.pi * f * t) * (0.5 ** i) for i, f in enumerate(chord))
    lfo = 0.6 + 0.4 * np.sin(2 * np.pi * 0.25 * t)
    return (sig * lfo / 6.0).astype(np.float32)

def _sfx(kind, dur):
    n = int(dur * SR); t = np.arange(n) / SR; out = np.zeros(n, np.float32)
    if kind == "pop":
        e = np.exp(-t * 18); out = np.sin(2 * np.pi * 660 * t) * e * 0.5
    elif kind == "whoosh":
        noise = np.random.randn(n) * np.exp(-((t - 0.15) ** 2) / 0.01)
        out = noise * 0.4
    elif kind == "alarm":
        beep = (np.sin(2 * np.pi * 880 * t) * (np.sin(2 * np.pi * 6 * t) > 0)) * np.exp(-t * 1.2)
        out = beep * 0.4
    elif kind == "chime":
        out = (np.sin(2 * np.pi * 1320 * t) + 0.5 * np.sin(2 * np.pi * 1980 * t)) * np.exp(-t * 3) * 0.4
    elif kind == "ghost":
        sweep = np.sin(2 * np.pi * (300 + 200 * np.sin(2 * np.pi * 1.5 * t)) * t)
        out = sweep * np.exp(-t * 1.5) * 0.35
    elif kind == "ambient":
        out = (np.random.randn(n) * 0.05) * (0.5 + 0.5 * np.sin(2 * np.pi * 0.5 * t))
    return out.astype(np.float32)

def _write_wav(path, sig):
    sig = np.clip(sig, -1, 1)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((sig * 32767).astype(np.int16).tobytes())


# ── image helpers ────────────────────────────────────────────────────────────
def _cover(img, w, h):
    iw, ih = img.size; s = max(w / iw, h / ih)
    img = img.resize((max(1, int(iw * s)), max(1, int(ih * s))), Image.Resampling.LANCZOS)
    x, y = (img.width - w) // 2, (img.height - h) // 2
    return img.crop((x, y, x + w, y + h))

def _emo(side, name):
    p = EMO / side / f"{name}.png"
    if not p.exists():
        p = EMO / side / "normal.png"
    return Image.open(p).convert("RGBA")

def _caption_png(lines):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    try: font = ImageFont.truetype(FONT, 50)
    except Exception: font = ImageFont.load_default()
    bar = Image.new("RGBA", (W, 280), (0, 0, 0, 0)); bd = ImageDraw.Draw(bar)
    for yy in range(280):
        bd.line([(0, yy), (W, yy)], fill=(8, 16, 22, int(190 * yy / 280)))
    img.alpha_composite(bar, (0, H - 280))
    y = H - 218
    for ln in lines:
        bb = d.textbbox((0, 0), ln, font=font); x = (W - (bb[2] - bb[0])) // 2
        d.text((x, y), ln, font=font, fill=(255, 255, 255, 255),
               stroke_width=6, stroke_fill=(8, 16, 22, 235)); y += 84
    return img


def main():
    tmp = Path(tempfile.mkdtemp())
    # Layout chosen by the vision-critic visual test (shiropico-layout-test.py):
    # ch_h=0.26 + "edges" placement → both characters fully visible, overlap=none, comp 85.
    ch_h = int(H * 0.26)
    edge_off = int(ch_h * 0.06)
    seg_videos, seg_audios = [], []
    for bi, (bg, se, pe, speaker, vname, caption, sfx, fx) in enumerate(BEATS):
        # voice + duration
        voice = _wav_read(VOICE / f"{vname}.wav") if vname and (VOICE / f"{vname}.wav").exists() else None
        dur = max(2.6, (len(voice) / SR + 1.0) if voice is not None else 3.2)
        nf = int(dur * FPS)
        # assets
        bgimg = _cover(Image.open(BG / f"{bg}.png").convert("RGB"), int(W * 1.12), int(H * 1.12))
        sh = _emo("shiro", se); pi = _emo("pico", pe)
        def fit(im):
            s = ch_h / im.height; return im.resize((int(im.width * s), ch_h), Image.Resampling.LANCZOS)
        sh, pi = fit(sh), fit(pi)
        cap = _caption_png(caption)
        # render frames
        fdir = tmp / f"b{bi:02d}"; fdir.mkdir()
        for f in range(nf):
            tt = f / FPS
            # Ken Burns: slow zoom-in on bg
            z = 1.0 + 0.06 * (f / max(1, nf))
            cw, ch = int(W / z), int(H / z)
            shake = int(6 * math.sin(tt * 40)) if fx == "shake" else 0
            x0 = (bgimg.width - cw) // 2 + shake; y0 = (bgimg.height - ch) // 2
            frame = bgimg.crop((x0, y0, x0 + cw, y0 + ch)).resize((W, H), Image.Resampling.LANCZOS).convert("RGBA")
            frame.alpha_composite(Image.new("RGBA", (W, H), (8, 14, 22, 90)))  # dim bg so chars pop
            # breathing bob + speaker talk-pop
            def place(img, side):
                bob = int(7 * math.sin(tt * 3.2 + (0 if side == "shiro" else 1.5)))
                talk = 1.0
                if speaker == side and voice is not None:
                    talk = 1.0 + 0.03 * abs(math.sin(tt * 13))
                im = img if talk == 1.0 else img.resize((int(img.width * talk), int(img.height * talk)), Image.Resampling.LANCZOS)
                # Face inward toward each other: flip シロ (left) so devices sit toward
                # the centre; ピコ (right) keeps her original facing. (vision-tested)
                if side == "shiro":
                    im = im.transpose(Image.Transpose.FLIP_LEFT_RIGHT); x = -edge_off
                else:
                    x = W - im.width + edge_off
                y = H - im.height - 240 + bob  # lift above the caption band
                frame.alpha_composite(im, (x, y))
            place(sh, "shiro"); place(pi, "pico")
            frame.alpha_composite(cap, (0, 0))
            # action flash (white fade at the start)
            if fx == "flash" and tt < 0.45:
                ov = Image.new("RGBA", (W, H), (255, 255, 255, int(150 * (1 - tt / 0.45))))
                frame.alpha_composite(ov)
            frame.convert("RGB").save(fdir / f"{f:04d}.png")
        seg = tmp / f"seg{bi:02d}.mp4"
        subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(fdir / "%04d.png"),
                        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(seg)],
                       capture_output=True, check=True)
        seg_videos.append(seg)
        # audio bed: BGM + sfx + voice
        bed = _bgm(dur)
        if sfx:
            s = _sfx(sfx, min(dur, 1.2)); bed[:len(s)] += s
        if voice is not None:
            lead = int(0.45 * SR); v = voice * 1.0
            end = min(len(bed), lead + len(v)); bed[lead:end] += v[:end - lead]
        wpath = tmp / f"aud{bi:02d}.wav"; _write_wav(wpath, bed)
        seg_audios.append(wpath)
    # concat video
    lv = tmp / "v.txt"; lv.write_text("".join(f"file '{p}'\n" for p in seg_videos))
    vcat = tmp / "vall.mp4"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lv),
                    "-c", "copy", str(vcat)], capture_output=True, check=True)
    # concat audio
    la = tmp / "a.txt"; la.write_text("".join(f"file '{p}'\n" for p in seg_audios))
    acat = tmp / "aall.wav"
    subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(la),
                    "-c", "copy", str(acat)], capture_output=True, check=True)
    out = OUT / "sp-ep01-motion-comic-v2.mp4"
    r = subprocess.run(["ffmpeg", "-y", "-i", str(vcat), "-i", str(acat),
                        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p",
                        "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)], capture_output=True, text=True)
    if r.returncode != 0:
        print("mux failed:\n", r.stderr[-800:]); return
    print(f"DONE → {out} ({out.stat().st_size // 1024} KB)")


if __name__ == "__main__":
    main()
