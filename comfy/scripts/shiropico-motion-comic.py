"""SHIRO & PICO — assemble generated ep01 panels into a motion comic (Ken Burns + captions).

ffmpeg zoompan (slow push/pan) over each panel + burned-in JP dialogue captions, concat → mp4.
VOICEVOX dialogue can be muxed later when the engine is reachable (see --voice TODO).

Out: data/ghosthacker-shiropico/resources/motion-comic/sp-ep01-motion-comic.mp4
"""
from __future__ import annotations
import os, subprocess, tempfile
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2] / "data/ghosthacker-shiropico"
PANELS = ROOT / "resources/panels"
OUT = ROOT / "resources/motion-comic"
OUT.mkdir(parents=True, exist_ok=True)
FONT = "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc"
if not os.path.exists(FONT):
    FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"

W, H, FPS = 1080, 1920, 30  # vertical short-form

# (panel filename stem, seconds, [caption lines], ken-burns mode)
BEATS = [
    ("p01-coldopen", 5, ["ドバイの夜。街じゅうの車が", "いっせいに眠りはじめた——"], "in"),
    ("p02-pico-iki", 4, ["ピコ「楽勝〜！オレ天才だし？」", "技、ワイルド・ピング！"], "left"),
    ("p02-pico-iki", 3, ["…が、眠りが伝染して増えていく", "ピコ「なんで増えんの!?」"], "right"),
    ("p03-shiro-fix", 5, ["シロ「——スリープ・コール。", "隔離して、正気に戻す。これがEDR」"], "in"),
    ("p04-henshin", 4, ["「シロピコ、オン！」", "ティールの光、等身アップ"], "out"),
    ("p05-ghost", 5, ["「消えたはずなのに、痕が残ってる。", "情報は物理だ。これは——Ghost だ」"], "in"),
]

def caption_png(lines, path):
    """Render caption lines to a transparent WxH PNG (white text + black stroke),
    bottom-anchored, so ffmpeg can overlay it fixed over the Ken-Burns panel."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(FONT, 52)
    except Exception:
        font = ImageFont.load_default()
    # translucent bottom gradient bar for legibility
    bar = Image.new("RGBA", (W, 300), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bar)
    for yy in range(300):
        bd.line([(0, yy), (W, yy)], fill=(8, 16, 22, int(180 * yy / 300)))
    img.alpha_composite(bar, (0, H - 300))
    y = H - 250
    for ln in lines:
        bb = d.textbbox((0, 0), ln, font=font)
        x = (W - (bb[2] - bb[0])) // 2
        d.text((x, y), ln, font=font, fill=(255, 255, 255, 255),
               stroke_width=6, stroke_fill=(8, 16, 22, 235))
        y += 86
    img.save(path)

def kb(mode, frames):
    # zoompan expressions per mode; output WxH
    z = "min(zoom+0.0010,1.25)" if mode in ("in", "left", "right") else "if(eq(on,0),1.25,max(zoom-0.0010,1.0))"
    if mode == "left":
        x, y = "x+1", "ih/2-(ih/zoom/2)"
    elif mode == "right":
        x, y = "x-1", "ih/2-(ih/zoom/2)"
    else:
        x, y = "iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"
    return (f"scale=-2:{H*2},zoompan=z='{z}':x='{x}':y='{y}':d={frames}:s={W}x{H}:fps={FPS}")

def main():
    seg_paths = []
    with tempfile.TemporaryDirectory() as td:
        for i, (stem, secs, lines, mode) in enumerate(BEATS):
            src = PANELS / f"sp-ep01-{stem}.png"
            if not src.exists():
                print(f"skip {stem}: missing"); continue
            frames = secs * FPS
            cap = os.path.join(td, f"cap{i:02d}.png")
            caption_png(lines, cap)
            seg = os.path.join(td, f"seg{i:02d}.mp4")
            # [0]=panel (Ken Burns) ; [1]=caption overlay (fixed)
            fc = f"[0:v]{kb(mode, frames)}[bg];[bg][1:v]overlay=0:0:format=auto,format=yuv420p[v]"
            cmd = ["ffmpeg", "-y", "-loop", "1", "-i", str(src), "-loop", "1", "-i", cap,
                   "-t", str(secs), "-filter_complex", fc, "-map", "[v]",
                   "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast",
                   "-pix_fmt", "yuv420p", seg]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode != 0:
                print(f"seg {stem} failed:\n{r.stderr[-800:]}"); continue
            seg_paths.append(seg)
            print(f"[{stem}] {secs}s -> seg{i:02d}")
        if not seg_paths:
            print("no segments"); return
        listf = os.path.join(td, "list.txt")
        Path(listf).write_text("".join(f"file '{p}'\n" for p in seg_paths))
        out = OUT / "sp-ep01-motion-comic.mp4"
        cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", listf,
               "-c:v", "libx264", "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", str(out)]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            print(f"concat failed:\n{r.stderr[-800:]}"); return
        sz = out.stat().st_size // 1024
        print(f"\nDONE -> {out} ({sz} KB, {sum(b[1] for b in BEATS)}s)")

if __name__ == "__main__":
    main()
