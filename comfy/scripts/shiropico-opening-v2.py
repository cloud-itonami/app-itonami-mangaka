"""SHIRO & PICO — cinematic OP v2 (Jujutsu/Kimetsu-grade direction), ~20s.

Uses the generated cinematic action cuts (resources/op-cuts/*.png) and cuts them
fast with OP grammar: push-in/pan/dutch camera, speed lines, impact flashes,
chromatic aberration, light leaks, particle bursts, vignette + an epic minor-key
theme song (riser → drop) synthesised in numpy + VOICEVOX title hooks.

Out: resources/opening/sp-opening-v2.mp4
"""
from __future__ import annotations
import math, os, subprocess, tempfile, wave
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageChops, ImageFilter

ROOT = Path(__file__).resolve().parents[2] / "data/ghosthacker-shiropico"
CUTS = ROOT / "resources/op-cuts"
VOICE = Path("/tmp/sp-voices")
OUT = ROOT / "resources/opening"; OUT.mkdir(parents=True, exist_ok=True)
FONT = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
if not os.path.exists(FONT):
    FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
W, H, FPS, SR = 1080, 1920, 30, 44100
TEAL = (41, 211, 194); LIME = (168, 224, 95); GOLD = (255, 209, 102)

# shot = (cut_png, dur, camera, fx_flags, [captions])
SHOTS = [
    ("01-city", 2.2, "push", ["flash_in", "title_ghost"], []),
    ("02-shiro-eye", 1.3, "punch", ["ca", "shake"], []),
    ("03-shiro-action", 2.4, "push", ["speed", "shake", "name_shiro"], []),
    ("04-pico-face", 1.3, "punch", ["ca"], []),
    ("05-pico-action", 2.4, "dutch", ["speed", "name_pico"], []),
    ("06-ghost", 2.2, "pullback", ["ca", "dread"], []),
    ("07-duo", 3.4, "push", ["speed", "burst", "tagline"], []),
    ("__title__", 4.6, "still", ["title_card"], []),
]


# ── theme song: epic minor-key build → drop ──────────────────────────────────
NOTE = {"A": 220, "C": 261.63, "D": 293.66, "E": 329.63, "F": 349.23, "G": 392,
        "A4": 440, "C5": 523.25, "D5": 587.33, "E5": 659.25, "F5": 698.46, "G5": 783.99, "A5": 880}
def _env(n, a, d, s, r):
    e = np.ones(n); ai, di, ri = int(a*SR), int(d*SR), int(r*SR)
    if ai: e[:ai] = np.linspace(0, 1, ai)
    if di: e[ai:ai+di] = np.linspace(1, s, di)
    e[ai+di:max(ai+di, n-ri)] = s
    if ri: e[n-ri:] = np.linspace(s, 0, ri)
    return e
def _o(freq, dur, kind="saw", vol=0.3, a=0.01, d=0.05, s=0.7, r=0.08):
    n = int(dur*SR); t = np.arange(n)/SR
    if kind == "saw": w = 2*(t*freq-np.floor(0.5+t*freq))
    elif kind == "square": w = np.sign(np.sin(2*np.pi*freq*t))
    else: w = np.sin(2*np.pi*freq*t)
    return (w*_env(n, a, d, s, r)*vol).astype(np.float32)
def _kick(d=0.2):
    n = int(d*SR); t = np.arange(n)/SR; return (np.sin(2*np.pi*(160*np.exp(-t*30)+45)*t)*np.exp(-t*9)*1.0).astype(np.float32)
def _snare(d=0.16):
    n = int(d*SR); t = np.arange(n)/SR; return ((np.random.randn(n)*0.6+np.sin(2*np.pi*200*t)*0.3)*np.exp(-t*18)*0.6).astype(np.float32)
def _hat(d=0.05):
    n = int(d*SR); return (np.random.randn(n)*np.exp(-np.arange(n)/SR*90)*0.2).astype(np.float32)
def _riser(d):
    n = int(d*SR); t = np.arange(n)/SR; f = 200*np.exp(t/d*2.0)
    return (np.sign(np.sin(2*np.pi*f*t))*(t/d)*0.4*np.random.uniform(0.8, 1.0)).astype(np.float32) + (np.random.randn(n)*(t/d)*0.15).astype(np.float32)

def theme(total):
    n = int(total*SR); mix = np.zeros(n, np.float32)
    bpm = 155; beat = 60/bpm; bar = beat*4
    def put(sig, at, g=1.0):
        i = int(at*SR); e = min(n, i+len(sig)); mix[i:e] += sig[:e-i]*g
    # Am - F - C - G (epic), per bar
    prog = [("A", "C", "E"), ("F", "A", "C5"), ("C", "E", "G"), ("G", "D5", "A4")]
    lead = [[("E5", 1), ("D5", 0.5), ("C5", 0.5), ("E5", 1), ("A5", 1)],
            [("F5", 1), ("E5", 1), ("C5", 2)],
            [("E5", 1), ("G5", 0.5), ("E5", 0.5), ("C5", 1), ("G", 1)],
            [("A5", 2), ("G5", 1), ("E5", 1)]]
    nb = int(total/bar)+1
    for b in range(nb):
        t0 = b*bar; ch = prog[b % 4]
        drop = (t0 >= 12.5)   # full energy from the duo/drop
        for k in range(4):
            put(_kick(), t0+k*beat, 1.0)
            put(_hat(), t0+k*beat+beat/2, 0.8 if drop else 0.4)
            if k in (1, 3): put(_snare(), t0+k*beat, 0.9 if drop else 0.5)
        put(_o(NOTE[ch[0]]/2, bar, "square", 0.24, s=0.85, r=0.05), t0)         # bass
        for nt in ch:
            put(_o(NOTE[nt], bar, "saw", 0.07 if not drop else 0.11, a=0.04, s=0.9, r=0.2), t0)  # pad
        if t0 >= 4:   # lead enters after intro
            mt = t0
            for nm, bts in lead[b % 4]:
                put(_o(NOTE.get(nm, NOTE["E5"]), beat*bts*0.95, "saw", 0.22 if not drop else 0.3, a=0.01, d=0.03, s=0.85, r=0.04), mt)
                mt += beat*bts
    put(_riser(2.2), 10.3)   # riser into the drop (duo)
    return np.tanh(mix*1.05)*0.92


# ── cinematic FX ─────────────────────────────────────────────────────────────
def _cover(img, w, h):
    iw, ih = img.size; s = max(w/iw, h/ih)
    img = img.resize((max(1, int(iw*s)), max(1, int(ih*s))), Image.Resampling.LANCZOS)
    x, y = (img.width-w)//2, (img.height-h)//2
    return img.crop((x, y, x+w, y+h))
def _vignette(fr):
    m = Image.new("L", (W, H), 0); d = ImageDraw.Draw(m)
    d.ellipse([-W*0.25, -H*0.18, W*1.25, H*1.18], fill=255)
    m = m.filter(ImageFilter.GaussianBlur(160))
    dark = Image.new("RGB", (W, H), (0, 0, 0))
    return Image.composite(fr, dark, m)
def _chroma(fr, px):
    r, g, b = fr.split()
    r = ImageChops.offset(r, px, 0); b = ImageChops.offset(b, -px, 0)
    return Image.merge("RGB", (r, g, b))
def _speedlines(d, cx, cy, t):
    import random; random.seed(int(t*60))
    for _ in range(60):
        a = random.uniform(0, 2*math.pi); r0 = random.uniform(W*0.36, W*0.5); r1 = r0+random.uniform(120, 360)
        col = (255, 255, 255, random.randint(60, 150))
        d.line([(cx+math.cos(a)*r0, cy+math.sin(a)*r0), (cx+math.cos(a)*r1, cy+math.sin(a)*r1)], fill=col, width=random.choice([2, 3, 5]))
# Cool display fonts (alphabet) — DIN Condensed / Impact for the logo, Avenir for subs.
TITLE_FONT = next((p for p in ["/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf",
                               "/System/Library/Fonts/Supplemental/Impact.ttf",
                               "/System/Library/Fonts/Supplemental/Arial Black.ttf"] if os.path.exists(p)), FONT)
SUB_FONT = next((p for p in ["/System/Library/Fonts/Avenir Next Condensed.ttc",
                             "/System/Library/Fonts/HelveticaNeue.ttc"] if os.path.exists(p)), FONT)
def _font(sz, path=None):
    try: return ImageFont.truetype(path or FONT, sz)
    except Exception: return ImageFont.load_default()
def _text(d, xy, s, f, fill, anchor="mm", stroke=10, sc=(6, 10, 16)):
    d.text(xy, s, font=f, fill=fill, anchor=anchor, stroke_width=stroke, stroke_fill=sc)

# Unix-terminal monospace (Menlo) for the GHOST HACKER wordmark.
MONO_FONT = next((p for p in ["/System/Library/Fonts/Menlo.ttc", "/System/Library/Fonts/SFNSMono.ttf",
                              "/System/Library/Fonts/Supplemental/Andale Mono.ttf"] if os.path.exists(p)), FONT)
def _mono(sz):
    for idx in (1, 0):  # Menlo.ttc: try Bold (1) then Regular (0)
        try: return ImageFont.truetype(MONO_FONT, sz, index=idx)
        except Exception: continue
    return _font(sz)

def _ghost_hacker(fr, cx, cy, sz, alpha):
    """GHOST HACKER wordmark: white monospace text, blue glow around it, shadow behind."""
    BLUE = (46, 134, 255); txt = "GHOST HACKER"; f = _mono(sz)
    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0)); gd = ImageDraw.Draw(glow)
    gd.text((cx, cy), txt, font=f, fill=(*BLUE, alpha), anchor="mm", stroke_width=14, stroke_fill=(*BLUE, alpha))
    fr.alpha_composite(glow.filter(ImageFilter.GaussianBlur(11)))           # blue glow (周囲に青)
    sh = Image.new("RGBA", (W, H), (0, 0, 0, 0)); sd = ImageDraw.Draw(sh)
    sd.text((cx + 5, cy + 9), txt, font=f, fill=(0, 0, 0, int(alpha * 0.75)), anchor="mm")
    fr.alpha_composite(sh.filter(ImageFilter.GaussianBlur(2)))              # shadow behind (後の影)
    ImageDraw.Draw(fr).text((cx, cy), txt, font=f, fill=(255, 255, 255, alpha),  # white text
                            anchor="mm", stroke_width=5, stroke_fill=(*BLUE, alpha))

def _glitch_logo(lines, cy, t, alpha):
    """Render alphabet title lines with a glitch look: RGB split + horizontal slice
    displacement + scanlines. `lines` = [(text, fontsize, color)]. Returns RGBA."""
    import random
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(layer)
    y = cy
    for txt, sz, col in lines:
        d.text((W // 2, y), txt, font=_font(sz, TITLE_FONT), fill=(*col, alpha),
               anchor="mm", stroke_width=6, stroke_fill=(4, 8, 12, alpha))
        y += int(sz * 0.92)
    # RGB channel split (chromatic glitch)
    r, g, b, a = layer.split()
    off = 7 + int(6 * math.sin(t * 30))
    r = ImageChops.offset(r, off, -2); b = ImageChops.offset(b, -off, 2)
    layer = Image.merge("RGBA", (r, g, b, a))
    # horizontal slice displacement (datamosh bars), seeded per ~6 frames
    random.seed(int(t * 5))
    out = layer.copy()
    for _ in range(random.randint(2, 5)):
        sy = random.randint(cy - 180, cy + 220); sh = random.randint(8, 34)
        dx = random.choice([-40, -22, 22, 40, 60])
        band = layer.crop((0, sy, W, sy + sh))
        out.paste(band, (dx, sy))
    # scanlines
    sl = Image.new("RGBA", (W, H), (0, 0, 0, 0)); sd = ImageDraw.Draw(sl)
    for yy in range(cy - 200, cy + 240, 4):
        sd.line([(0, yy), (W, yy)], fill=(0, 0, 0, 60), width=1)
    out.alpha_composite(sl)
    return out
def _wav(p):
    with wave.open(str(p), "rb") as w:
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32)/32768.0; sr = w.getframerate()
        if w.getnchannels() == 2: a = a.reshape(-1, 2).mean(1)
    if sr != SR: a = np.interp(np.linspace(0, len(a), int(len(a)*SR/sr)), np.arange(len(a)), a)
    return a


def build():
    tmp = Path(tempfile.mkdtemp()); fdir = tmp/"f"; fdir.mkdir()
    imgs = {}
    for p in CUTS.glob("*.png"):
        imgs[p.stem] = _cover(Image.open(p).convert("RGB"), int(W*1.25), int(H*1.25))
    total = sum(s[1] for s in SHOTS); f_global = 0
    rng = np.random.default_rng(3); parts = rng.uniform([0, 0], [W, H], (70, 2))
    for (cut, dur, cam, fx, _caps) in SHOTS:
        nf = int(dur*FPS)
        for f in range(nf):
            tt = f/nf  # 0..1 within shot
            gt = f_global/FPS
            if cut == "__title__":
                base = Image.new("RGB", (W, H), (7, 11, 18))
            else:
                src = imgs.get(cut) or next(iter(imgs.values()))
                # camera
                if cam == "push": z = 1.18-0.16*tt
                elif cam == "pullback": z = 1.02+0.18*tt
                elif cam == "punch": z = 1.30-0.10*tt
                elif cam == "dutch": z = 1.16-0.10*tt
                else: z = 1.1
                cw, ch = int(W*z), int(H*z)
                sx = int((src.width-cw)/2 + (40*math.sin(gt*7) if "shake" in fx else 0) + (cw*0.06*math.sin(tt*math.pi) if cam == "dutch" else 0))
                sy = int((src.height-ch)/2)
                base = src.crop((sx, sy, sx+cw, sy+ch)).resize((W, H), Image.Resampling.LANCZOS)
                if cam == "dutch":
                    base = base.rotate(6, expand=False, resample=Image.Resampling.BILINEAR)
            if "ca" in fx:
                base = _chroma(base, 6+int(4*math.sin(gt*20)))
            base = _vignette(base)
            fr = base.convert("RGBA"); d = ImageDraw.Draw(fr)
            # drifting particles (subtle, all shots)
            for i, (px, py) in enumerate(parts):
                yy = int((py-gt*110-i*4) % H); col = TEAL if i % 3 else LIME
                d.rectangle([px, yy, px+3, yy+9], fill=(*col, 110))
            if "speed" in fx:
                _speedlines(d, W//2, int(H*0.42), gt)
            if "burst" in fx and tt < 0.5:
                d.ellipse([W//2-int(900*tt), H//2-int(900*tt), W//2+int(900*tt), H//2+int(900*tt)],
                          outline=(255, 255, 255, int(200*(1-tt*2))), width=14)
            if "dread" in fx:
                fr.alpha_composite(Image.new("RGBA", (W, H), (60, 0, 30, int(40+30*math.sin(gt*4)))))
            # text
            # ── alphabet-only text (overseas-first), cool display fonts ──
            if "title_ghost" in fx and tt > 0.3:
                a = int(min(255, (tt-0.3)*500))
                _ghost_hacker(fr, W//2, H//2, 86, a)
            if "name_shiro" in fx:
                _text(d, (W//2, 300), "SHIRO", _font(150, TITLE_FONT), (*TEAL, 255), stroke=12)
                _text(d, (W//2, 400), "ELITE WHITE-HAT HACKER", _font(40, SUB_FONT), (255, 255, 255, 255), stroke=6)
            if "name_pico" in fx:
                _text(d, (W//2, 300), "PICO", _font(150, TITLE_FONT), (*LIME, 255), stroke=12)
                _text(d, (W//2, 400), "GENIUS KID", _font(40, SUB_FONT), (255, 255, 255, 255), stroke=6)
            if "tagline" in fx:
                _text(d, (W//2, 360), "FROM STEALING", _font(72, TITLE_FONT), (*GOLD, 255), stroke=10)
                _text(d, (W//2, 450), "TO PROTECTING.", _font(72, TITLE_FONT), (255, 255, 255, 255), stroke=10)
            if "title_card" in fx:
                a = int(min(255, tt*520))
                d.rounded_rectangle([70, H//2-250, W-70, H//2+210], radius=10, fill=(6, 12, 20, min(200, a)),
                                    outline=(*TEAL, a), width=6)
                # corner ticks for a HUD look
                for cx2, cy2 in [(70, H//2-250), (W-70, H//2-250), (70, H//2+210), (W-70, H//2+210)]:
                    sx = 40 if cx2 < W//2 else -40; sy2 = 40 if cy2 < H//2 else -40
                    d.line([(cx2, cy2), (cx2+sx, cy2)], fill=(*TEAL, a), width=6)
                    d.line([(cx2, cy2), (cx2, cy2+sy2)], fill=(*TEAL, a), width=6)
                fr.alpha_composite(_glitch_logo([("SHIRO & PICO", 156, TEAL)], H//2-70, gt, a))
                _ghost_hacker(fr, W//2, H//2+100, 50, a)
                _text(d, (W//2, H//2+172), "T H E   A N I M A T I O N", _font(34, SUB_FONT), (*GOLD, a), stroke=5)
            # cut-transition white flash (first 3 frames of each shot, + flash_in)
            if f < 3 or ("flash_in" in fx and gt < 0.4):
                fr.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, 120 if f < 3 else int(255*(1-gt/0.4)))))
            fr.convert("RGB").save(fdir/f"{f_global:04d}.png"); f_global += 1
    seg = tmp/"v.mp4"
    subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(fdir/"%04d.png"),
                    "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", str(seg)],
                   capture_output=True, check=True)
    aud = theme(total)
    def mix(name, at, g=1.1):
        p = VOICE/f"{name}.wav"
        if p.exists():
            v = _wav(p)*g; i = int(at*SR); e = min(len(aud), i+len(v)); aud[i:e] += v[:e-i]
    mix("op_pico", 12.7)      # battle shout into the drop
    mix("op_title", total-3.8)  # title call
    aud = np.clip(aud, -1, 1); aw = tmp/"a.wav"
    with wave.open(str(aw), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((aud*32767).astype(np.int16).tobytes())
    out = OUT/"sp-opening-v2.mp4"
    r = subprocess.run(["ffmpeg", "-y", "-i", str(seg), "-i", str(aw), "-c:v", "copy",
                        "-c:a", "aac", "-b:a", "192k", "-shortest", str(out)], capture_output=True, text=True)
    if r.returncode != 0:
        print("mux fail:\n", r.stderr[-700:]); return
    print(f"DONE → {out} ({out.stat().st_size//1024} KB, {total:.1f}s)")


if __name__ == "__main__":
    build()
