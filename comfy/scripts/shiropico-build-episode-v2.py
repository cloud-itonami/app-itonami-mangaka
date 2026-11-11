"""Build SHIRO & PICO episode v2 from shotlist-v2 — dialogue-only + generated scene cuts.

- SCENE beat: full-frame generated scene image (resources/ep-scenes/<key>.png), Ken Burns,
  NO characters, NO caption — a real scene-change cut (replaces narration).
- DIALOGUE beat: the current scene image (dimmed) as backdrop + on-model 立ち絵
  (shiro flipped inward) + the SPOKEN LINE as caption + VOICEVOX voice. No narration.
- BGM: reusable library (resources/bgm/*.wav) picked by mood, looped continuously.
Prepends the cinematic OP. VOICEVOX at localhost:50021 (port-forward) for voice.

Out: resources/episode/sp-ep01-v2.mp4
"""
from __future__ import annotations
import hashlib, json, math, os, subprocess, tempfile, wave
from pathlib import Path
import numpy as np
import httpx
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2] / "data/ghosthacker-shiropico"
SCN = ROOT / "resources/ep-scenes"
BG = ROOT / "resources/bg2"
EMO = ROOT / "character-refs/emotions"
BGM = ROOT / "resources/bgm"
OP = ROOT / "resources/opening/sp-opening-v2.mp4"
SHOTLIST = ROOT / "episode-01-shotlist-v2.json"
OUT = ROOT / "resources/episode"; OUT.mkdir(parents=True, exist_ok=True)
VCACHE = Path("/tmp/sp-vcache"); VCACHE.mkdir(exist_ok=True)
VV = "http://localhost:50021"
FONT = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
if not os.path.exists(FONT): FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
W, H, FPS, SR = 1080, 1920, 30, 44100
SPK = {"shiro": 2, "pico": 3}


def voicevox(text, speaker):
    key = hashlib.md5(f"{speaker}:{text}".encode()).hexdigest()[:16]; c = VCACHE / f"{key}.wav"
    if c.exists(): return c
    try:
        q = httpx.post(f"{VV}/audio_query", params={"text": text, "speaker": speaker}, timeout=30).json()
        q["speedScale"] = 0.97
        w = httpx.post(f"{VV}/synthesis", params={"speaker": speaker}, json=q, headers={"accept": "audio/wav"}, timeout=30)
        if w.status_code == 200 and w.content: c.write_bytes(w.content); return c
    except Exception as e: print("  vv err", str(e)[:60])
    return None

def _wav(p):
    with wave.open(str(p), "rb") as w:
        a = np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768.0; sr = w.getframerate()
        if w.getnchannels() == 2: a = a.reshape(-1, 2).mean(1)
    if sr != SR: a = np.interp(np.linspace(0, len(a), int(len(a) * SR / sr)), np.arange(len(a)), a)
    return a

def _sfx(kind, dur):
    n = int(dur * SR); t = np.arange(n) / SR
    if kind == "pop": return (np.sin(2*np.pi*660*t)*np.exp(-t*18)*0.5).astype(np.float32)
    if kind == "whoosh": return (np.random.randn(n)*np.exp(-((t-0.15)**2)/0.01)*0.4).astype(np.float32)
    if kind == "alarm": return ((np.sin(2*np.pi*880*t)*(np.sin(2*np.pi*6*t)>0))*np.exp(-t*1.2)*0.4).astype(np.float32)
    if kind == "chime": return ((np.sin(2*np.pi*1320*t)+0.5*np.sin(2*np.pi*1980*t))*np.exp(-t*3)*0.4).astype(np.float32)
    if kind == "ghost": return (np.sin(2*np.pi*(300+200*np.sin(2*np.pi*1.5*t))*t)*np.exp(-t*1.5)*0.35).astype(np.float32)
    if kind == "ambient": return (np.random.randn(n)*0.05*(0.5+0.5*np.sin(2*np.pi*0.5*t))).astype(np.float32)
    return np.zeros(n, np.float32)

def _cover(img, w, h):
    iw, ih = img.size; s = max(w/iw, h/ih)
    img = img.resize((max(1, int(iw*s)), max(1, int(ih*s))), Image.Resampling.LANCZOS)
    x, y = (img.width-w)//2, (img.height-h)//2
    return img.crop((x, y, x+w, y+h))
def _emo(side, name):
    p = EMO/side/f"{name}.png"; return Image.open(p if p.exists() else EMO/side/"normal.png").convert("RGBA")
def _caption(text):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0)); d = ImageDraw.Draw(img)
    try: font = ImageFont.truetype(FONT, 50)
    except Exception: font = ImageFont.load_default()
    lines, cur = [], ""
    for ch in text:
        if len(cur) >= 20 and ch in "、。！？ 　": lines.append(cur+(ch if ch.strip() else "")); cur = ""
        else: cur += ch
    if cur: lines.append(cur)
    lines = lines[:3]
    bar = Image.new("RGBA", (W, 290), (0, 0, 0, 0)); bd = ImageDraw.Draw(bar)
    for yy in range(290): bd.line([(0, yy), (W, yy)], fill=(8, 16, 22, int(200*yy/290)))
    img.alpha_composite(bar, (0, H-290)); y = H-240
    for ln in lines:
        bb = d.textbbox((0, 0), ln, font=font); d.text(((W-(bb[2]-bb[0]))//2, y), ln, font=font, fill=(255, 255, 255, 255), stroke_width=6, stroke_fill=(8, 16, 22, 235)); y += 80
    return img

def mood_of(b):
    k = (b.get("scene_key") or ""); sfx = b.get("sfx") or ""; spk = b.get("speaker"); pe = b.get("pico_emo", "")
    if "ghost" in k or sfx == "ghost": return "mystery"
    if any(x in k for x in ["henshin", "victory", "purify"]): return "victory"
    if any(x in k for x in ["wild-ping", "pulse", "lure", "horde", "contagion", "antenna", "siem"]) or sfx in ("alarm", "whoosh"): return "action"
    if any(x in k for x in ["crosswalk", "parent"]): return "tension"
    if str(b.get("scene")) == "codex" or "codex" in k: return "codex"
    if spk == "pico" and pe in ("panic", "smug", "happy", "confused"): return "comedy"
    return "daily"


def build():
    beats = json.loads(SHOTLIST.read_text())
    bgm = {p.stem: _wav(p) for p in BGM.glob("*.wav")}
    offs = {k: 0 for k in bgm}
    def bgm_bed(name, dur):
        track = bgm.get(name)
        if track is None:
            track = next(iter(bgm.values()))
        need = int(dur*SR); out = np.zeros(need, np.float32); o = offs.get(name, 0); i = 0
        while i < need:
            chunk = track[o:o+(need-i)]
            if len(chunk) == 0: o = 0; continue
            out[i:i+len(chunk)] = chunk; i += len(chunk); o = (o+len(chunk)) % len(track)
        offs[name] = o
        f = int(0.03*SR); out[:f] *= np.linspace(0, 1, f); out[-f:] *= np.linspace(1, 0, f)
        return out*0.33
    # fallback bg if a scene image missing
    fallback = _cover(Image.open(BG/"bg-dubai-night.png").convert("RGB"), int(W*1.12), int(H*1.12))
    def scene_img(key):
        p = SCN/f"{key}.png"
        return _cover(Image.open(p).convert("RGB"), int(W*1.12), int(H*1.12)) if p.exists() else fallback
    cur_bg = fallback
    ch_h = int(H*0.26); eo = int(ch_h*0.06)
    tmp = Path(tempfile.mkdtemp()); seg_v, seg_a = [], []
    for bi, b in enumerate(beats):
        typ = b.get("type"); fx = b.get("fx"); sfx = b.get("sfx")
        if typ == "scene":
            cur_bg = scene_img(b.get("scene_key", ""))
            dur = float(b.get("dur") or 2.6); voice = None; text = ""
        else:
            spk = b.get("speaker"); text = (b.get("text") or "").strip()
            voice = None
            if spk in SPK and text:
                wp = voicevox(text, SPK[spk]);  voice = _wav(wp) if wp else None
            dur = max(2.2, (len(voice)/SR+0.85) if voice is not None else 2.6)
        nf = int(dur*FPS)
        sh = _emo("shiro", b.get("shiro_emo", "normal")); pi = _emo("pico", b.get("pico_emo", "normal"))
        def fit(im): s = ch_h/im.height; return im.resize((int(im.width*s), ch_h), Image.Resampling.LANCZOS)
        sh, pi = fit(sh), fit(pi)
        cap = _caption(text) if (typ == "dialogue" and text) else None
        fdir = tmp/f"b{bi:03d}"; fdir.mkdir()
        for f in range(nf):
            tt = f/FPS; z = 1.0+(0.07 if typ == "scene" else 0.05)*(f/max(1, nf))
            cw, chh = int(W/z), int(H/z)
            shake = int(8*math.sin(tt*40)) if fx == "shake" else 0
            x0 = (cur_bg.width-cw)//2+shake; y0 = (cur_bg.height-chh)//2
            fr = cur_bg.crop((x0, y0, x0+cw, y0+chh)).resize((W, H), Image.Resampling.LANCZOS).convert("RGBA")
            if typ == "dialogue":
                fr.alpha_composite(Image.new("RGBA", (W, H), (8, 14, 22, 110)))  # dim for talking heads
                spk = b.get("speaker")
                def place(img, side):
                    bob = int(7*math.sin(tt*3.2+(0 if side == "shiro" else 1.5))); im = img
                    if spk == side and voice is not None:
                        sc = 1.0+0.03*abs(math.sin(tt*13)); im = img.resize((int(img.width*sc), int(img.height*sc)), Image.Resampling.LANCZOS)
                    if side == "shiro": im = im.transpose(Image.Transpose.FLIP_LEFT_RIGHT); x = -eo
                    else: x = W-im.width+eo
                    fr.alpha_composite(im, (x, H-im.height-240+bob))
                place(sh, "shiro"); place(pi, "pico")
                if cap: fr.alpha_composite(cap)
            if fx == "flash" and tt < 0.4:
                fr.alpha_composite(Image.new("RGBA", (W, H), (255, 255, 255, int(160*(1-tt/0.4)))))
            fr.convert("RGB").save(fdir/f"{f:04d}.png")
        seg = tmp/f"s{bi:03d}.mp4"
        subprocess.run(["ffmpeg", "-y", "-framerate", str(FPS), "-i", str(fdir/"%04d.png"),
                        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p", str(seg)], capture_output=True, check=True)
        seg_v.append(seg)
        bed = bgm_bed(mood_of(b), dur)
        if sfx and sfx != "null":
            s = _sfx(sfx, min(dur, 1.2)); bed[:len(s)] += s
        if voice is not None:
            lead = int(0.4*SR); end = min(len(bed), lead+len(voice)); bed[lead:end] += voice[:end-lead]
        ap = tmp/f"a{bi:03d}.wav"
        with wave.open(str(ap), "wb") as w:
            w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR); w.writeframes((np.clip(bed, -1, 1)*32767).astype(np.int16).tobytes())
        seg_a.append(ap)
        if bi % 8 == 0: print(f"  beat {bi}/{len(beats)} ({typ})", flush=True)
    lv = tmp/"v.txt"; lv.write_text("".join(f"file '{p}'\n" for p in seg_v))
    bv = tmp/"bv.mp4"; subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lv), "-c", "copy", str(bv)], capture_output=True, check=True)
    la = tmp/"a.txt"; la.write_text("".join(f"file '{p}'\n" for p in seg_a))
    ba = tmp/"ba.wav"; subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(la), "-c", "copy", str(ba)], capture_output=True, check=True)
    body = tmp/"body.mp4"
    subprocess.run(["ffmpeg", "-y", "-i", str(bv), "-i", str(ba), "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k", "-pix_fmt", "yuv420p", "-shortest", str(body)], capture_output=True, check=True)
    parts = [OP, body] if OP.exists() else [body]; norm = []
    for i, p in enumerate(parts):
        np_out = tmp/f"n{i}.mp4"
        subprocess.run(["ffmpeg", "-y", "-i", str(p), "-vf", f"scale={W}:{H}:force_original_aspect_ratio=decrease,pad={W}:{H}:(ow-iw)/2:(oh-ih)/2,fps={FPS}",
                        "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-c:a", "aac", "-b:a", "160k", "-ar", str(SR), "-pix_fmt", "yuv420p", str(np_out)], capture_output=True, check=True)
        norm.append(np_out)
    lf = tmp/"f.txt"; lf.write_text("".join(f"file '{p}'\n" for p in norm))
    out = OUT/"sp-ep01-v2.mp4"
    r = subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(lf), "-c", "copy", str(out)], capture_output=True, text=True)
    if r.returncode != 0: print("concat fail:\n", r.stderr[-700:]); return
    dur = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)], capture_output=True, text=True).stdout.strip()
    print(f"DONE → {out} ({out.stat().st_size//1024} KB, {dur}s)")

if __name__ == "__main__":
    build()
