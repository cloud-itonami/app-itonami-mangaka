"""SHIRO & PICO — opening movie + theme song (numpy-synth chiptune cyber pop).

~18s vertical OP: cyber-city build → シロ reveal → ピコ reveal → duo + tagline →
title card. Original theme song synthesised in numpy (drums + bass + pad + lead,
A-major I–V–vi–IV) with VOICEVOX title hooks. No external assets beyond the
character 立ち絵 + generated backgrounds.

Out: resources/opening/sp-opening.mp4
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
OUT = ROOT / "resources/opening"; OUT.mkdir(parents=True, exist_ok=True)
FONT = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
FONTB = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
if not os.path.exists(FONT):
    FONT = FONTB = "/System/Library/Fonts/Hiragino Sans GB.ttc"
W, H, FPS, SR = 1080, 1920, 30, 44100
TEAL = (41, 211, 194); LIME = (168, 224, 95); GOLD = (255, 209, 102)

# ── theme song ───────────────────────────────────────────────────────────────
NOTE = {"A": 440.0, "B": 493.88, "C#": 554.37, "D": 587.33, "E": 659.25,
        "F#": 739.99, "G#": 830.61, "A2": 880.0, "B2": 987.77, "C#2": 1108.73, "D2": 1174.66, "E2": 1318.5}
def _adsr(n, a=0.01, d=0.05, s=0.7, r=0.1):
    env = np.ones(n); ai, di, ri = int(a*SR), int(d*SR), int(r*SR)
    if ai: env[:ai] = np.linspace(0, 1, ai)
    if di: env[ai:ai+di] = np.linspace(1, s, di)
    env[ai+di:n-ri] = s
    if ri: env[n-ri:] = np.linspace(s, 0, ri)
    return env
def _osc(freq, dur, kind="square", vol=0.3, a=0.01, d=0.05, s=0.7, r=0.08):
    n = int(dur*SR); t = np.arange(n)/SR
    if kind == "square": w = np.sign(np.sin(2*np.pi*freq*t))
    elif kind == "saw": w = 2*(t*freq - np.floor(0.5+t*freq))
    else: w = np.sin(2*np.pi*freq*t)
    return (w * _adsr(n, a, d, s, r) * vol).astype(np.float32)
def _kick(dur=0.18):
    n = int(dur*SR); t = np.arange(n)/SR
    f = 150*np.exp(-t*30)+50
    return (np.sin(2*np.pi*f*t)*np.exp(-t*12)*0.9).astype(np.float32)
def _hat(dur=0.05):
    n = int(dur*SR); return (np.random.randn(n)*np.exp(-np.arange(n)/SR*80)*0.18).astype(np.float32)
def _snare(dur=0.12):
    n = int(dur*SR); t=np.arange(n)/SR
    return ((np.random.randn(n)*0.5+np.sin(2*np.pi*180*t)*0.3)*np.exp(-t*22)*0.5).astype(np.float32)

def theme_song(total_sec):
    n = int(total_sec*SR); mix = np.zeros(n, np.float32)
    bpm = 150; beat = 60/bpm; bar = beat*4
    def put(sig, at):
        i = int(at*SR); e = min(n, i+len(sig)); mix[i:e] += sig[:e-i]
    # chord roots per bar: A E F# D (I V vi IV), loop
    roots = [("A", "C#", "E"), ("E", "G#", "B"), ("F#", "A", "C#2"), ("D", "F#", "A2")]
    melody = [  # (note, beats) per bar, a catchy hook
        [("E2",1),("C#2",0.5),("D2",0.5),("E2",1),("B2",1)],
        [("G#",1),("B2",1),("E2",2)],
        [("F#",1),("A2",0.5),("B2",0.5),("C#2",1),("A2",1)],
        [("D2",1),("F#",1),("A2",1),("E2",1)],
    ]
    nbars = int(total_sec/bar)+1
    for b in range(nbars):
        t0 = b*bar; ch = roots[b % 4]
        # drums
        for k in range(4):
            put(_kick(), t0+k*beat)
            put(_hat(), t0+k*beat+beat/2)
            if k in (1, 3): put(_snare(), t0+k*beat)
        # bass (root, square low)
        put(_osc(NOTE[ch[0]]/2, bar, "square", 0.22, s=0.8, r=0.05), t0)
        # pad (triad sustained, sine)
        for nt in ch:
            put(_osc(NOTE[nt]/2, bar, "sine", 0.10, a=0.05, s=0.9, r=0.2), t0)
        # lead melody (square)
        mt = t0
        for note, bts in melody[b % 4]:
            put(_osc(NOTE[note], beat*bts*0.92, "square", 0.26, a=0.01, d=0.03, s=0.85, r=0.04), mt)
            mt += beat*bts
    # gentle master limiter
    mix = np.tanh(mix*1.1)*0.9
    return mix[:n]


# ── visuals ──────────────────────────────────────────────────────────────────
def _cover(img, w, h):
    iw, ih = img.size; s = max(w/iw, h/ih)
    img = img.resize((max(1, int(iw*s)), max(1, int(ih*s))), Image.Resampling.LANCZOS)
    x, y = (img.width-w)//2, (img.height-h)//2
    return img.crop((x, y, x+w, y+h))
def _emo(side, name="normal"):
    p = EMO/side/f"{name}.png"
    return Image.open(p if p.exists() else EMO/side/"normal.png").convert("RGBA")
def _font(sz):
    try: return ImageFont.truetype(FONT, sz)
    except Exception: return ImageFont.load_default()
def _text(d, xy, s, font, fill, anchor="mm", stroke=8, sc=(8, 14, 22)):
    d.text(xy, s, font=font, fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=sc)

def _wav_read(p):
    with wave.open(str(p), "rb") as w:
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)/32768.0
        sr = w.getframerate()
        if w.getnchannels() == 2: a = a.reshape(-1, 2).mean(1)
    if sr != SR: a = np.interp(np.linspace(0, len(a), int(len(a)*SR/sr)), np.arange(len(a)), a)
    return a


def build():
    tmp = Path(tempfile.mkdtemp())
    total = 18.0
    nf = int(total*FPS)
    city = _cover(Image.open(BG/"bg-dubai-night.png").convert("RGB"), int(W*1.15), int(H*1.15))
    sky = _cover(Image.open(BG/"bg-skyscraper-ghost.png").convert("RGB"), int(W*1.15), int(H*1.15))
    shiro = _emo("shiro", "happy"); pico = _emo("pico", "happy")
    shiro = shiro.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    def fit(im, h):
        s = h/im.height; return im.resize((int(im.width*s), h), Image.Resampling.LANCZOS)
    rng = np.random.default_rng(7)
    parts = rng.uniform([0, 0], [W, H], (90, 2))
    fdir = tmp/"f"; fdir.mkdir()
    for f in range(nf):
        t = f/FPS
        # background per phase
        bg = (city if t < 11 else sky)
        z = 1.0+0.05*(f/nf)
        cw, ch = int(W/z), int(H/z)
        x0, y0 = (bg.width-cw)//2, (bg.height-ch)//2
        fr = bg.crop((x0, y0, x0+cw, y0+ch)).resize((W, H), Image.Resampling.LANCZOS).convert("RGBA")
        fr.alpha_composite(Image.new("RGBA", (W, H), (8, 12, 20, 110)))
        d = ImageDraw.Draw(fr)
        # teal data particles drifting up
        for i, (px, py) in enumerate(parts):
            yy = int((py - t*120 - i*3) % H)
            a = 120 + int(80*math.sin(t*3+i))
            d.rectangle([px, yy, px+3, yy+10], fill=(*TEAL, max(40, a)))
        # ── phases ──
        if t < 4:   # build: title sub
            if t > 1:
                a = int(min(255, (t-1)*255))
                _text(d, (W//2, H//2-40), "GHOST HACKER", _font(86), (*TEAL, a), stroke=10)
                _text(d, (W//2, H//2+60), "シリーズ", _font(44), (255, 255, 255, a), stroke=6)
        elif t < 7.5:  # シロ reveal (slide from left)
            p = min(1, (t-4)/0.5); sh = fit(shiro, int(H*0.5))
            x = int(-sh.width + (60+sh.width)*p)
            fr.alpha_composite(sh, (x, H-sh.height-360+int(8*math.sin(t*4))))
            _text(d, (W//2+120, 360), "シロ", _font(96), (*TEAL, 255), stroke=10)
            _text(d, (W//2+120, 470), "世界トップのホワイトハッカー", _font(38), (255, 255, 255, 255), stroke=6)
        elif t < 11:  # ピコ reveal (slide from right)
            p = min(1, (t-7.5)/0.5); pi = fit(pico, int(H*0.5))
            x = int(W - (60+pi.width)*p)
            fr.alpha_composite(pi, (x, H-pi.height-360+int(8*math.sin(t*4+1.5))))
            _text(d, (W//2-120, 360), "ピコ", _font(96), (*LIME, 255), stroke=10)
            _text(d, (W//2-120, 470), "天才キッズ", _font(38), (255, 255, 255, 255), stroke=6)
        elif t < 14.5:  # duo + tagline + action flashes
            sh = fit(shiro, int(H*0.42)); pi = fit(pico, int(H*0.42))
            bob = int(10*math.sin(t*5))
            fr.alpha_composite(sh, (40, H-sh.height-300+bob))
            fr.alpha_composite(pi, (W-pi.width-40, H-pi.height-300-bob))
            _text(d, (W//2, 420), "盗む力から、", _font(64), (*GOLD, 255), stroke=9)
            _text(d, (W//2, 510), "守る力へ。", _font(64), (255, 255, 255, 255), stroke=9)
            if math.sin(t*9) > 0.7:
                fr.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, 60)))
        else:  # title card
            a = int(min(255, (t-14.5)*340))
            d.rounded_rectangle([90, H//2-220, W-90, H//2+200], radius=40,
                                fill=(8, 16, 24, min(200, a)), outline=(*TEAL, a), width=8)
            _text(d, (W//2, H//2-70), "SHIRO", _font(150), (*TEAL, a), stroke=12)
            _text(d, (W//2, H//2+80), "& PICO", _font(150), (255, 255, 255, a), stroke=12)
            _text(d, (W//2, H//2+200), "ゴーストハッカー", _font(46), (*GOLD, a), stroke=7)
        if t < 0.4:  # open flash
            fr.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, int(255*(1-t/0.4)))))
        fr.convert("RGB").save(fdir/f"{f:04d}.png")
    # video
    seg = tmp/"v.mp4"
    subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(fdir/"%04d.png"),
                    "-c:v", "libx264", "-preset", "medium", "-crf", "19", "-pix_fmt", "yuv420p", str(seg)],
                   capture_output=True, check=True)
    # audio: theme + voice hooks
    aud = theme_song(total)
    def mixin(name, at, gain=1.0):
        p = VOICE/f"{name}.wav"
        if p.exists():
            v = _wav_read(p)*gain; i = int(at*SR); e = min(len(aud), i+len(v)); aud[i:e] += v[:e-i]
    mixin("op_pico", 4.2, 1.1)      # "シロ＆ピコ、いっくよー！" at reveal
    mixin("op_title", 14.7, 1.2)    # "ゴーストハッカー！" at title
    aud = np.clip(aud, -1, 1)
    awav = tmp/"a.wav"
    with wave.open(str(awav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((aud*32767).astype(np.int16).tobytes())
    out = OUT/"sp-opening.mp4"
    r = subprocess.run(["ffmpeg", "-y", "-i", str(seg), "-i", str(awav),
                        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)],
                       capture_output=True, text=True)
    if r.returncode != 0:
        print("mux fail:\n", r.stderr[-700:]); return
    print(f"DONE → {out} ({out.stat().st_size//1024} KB, {total:.0f}s)")


if __name__ == "__main__":
    build()
