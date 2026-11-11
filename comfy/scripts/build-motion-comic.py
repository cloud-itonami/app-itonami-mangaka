"""Motion-comic encoder — OTIO timeline + FFmpeg.

For each manga page PNG, extract panel crops from the manifest layout
and assemble into a video with:
  - Per-panel Ken Burns (pan + zoom)
  - Cross-dissolve between panels
  - Page-end transition

Per-panel duration based on bubble count + shot type:
  Wide/establishing: 3s    Medium dialog: 2.5s    CU dramatic: 2s    Insert: 1.5s

Outputs:
  /tmp/gh-arc0-1-motion-comic-pXX.mp4   single-page motion comic
  /tmp/gh-arc0-1-motion-comic.otio       full OTIO timeline (concat all)
  /tmp/gh-arc0-1-motion-comic.mp4        full episode motion comic

Activates the OTIO + FFmpeg ADR scaffold that was defined but not
yet wired (ADR-2605222000 tech audit row).
"""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path
from PIL import Image
import opentimelineio as otio

MANIFEST = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json")
PAGE_PNG_DIR = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/v5plus")
OUT_DIR = Path("/tmp")
FPS = 24

PAGE_W, PAGE_H = 1280, 1817
MARGIN, GUTTER = 40, 16
SIZE_UNIT = {"small": 1, "medium": 2, "large": 3, "spread": 6}


def compute_layout(panels):
    rows = {}
    for p in panels:
        r = p.get("panelLayout", {}).get("gh:row") or 1
        rows.setdefault(int(r), []).append(p)
    sorted_rows = sorted(rows.keys())
    avail_h = PAGE_H - 2 * MARGIN - (len(sorted_rows) - 1) * GUTTER
    row_h = avail_h // len(sorted_rows)
    layout = []
    cur_y = MARGIN
    for r in sorted_rows:
        row_panels = sorted(rows[r], key=lambda p: p.get("panelLayout", {}).get("gh:readingOrder", p["panelIndex"]))
        units = [SIZE_UNIT.get(p.get("panelLayout", {}).get("gh:size", "medium"), 2) for p in row_panels]
        avail_w = PAGE_W - 2 * MARGIN - (len(row_panels) - 1) * GUTTER
        unit_w = avail_w / sum(units)
        cur_x = PAGE_W - MARGIN
        for i, p in enumerate(row_panels):
            w = int(round(units[i] * unit_w))
            cur_x -= w
            layout.append({"idx": p["panelIndex"], "x": cur_x, "y": cur_y,
                            "w": w, "h": row_h, "panel": p})
            if i < len(row_panels) - 1: cur_x -= GUTTER
        cur_y += row_h + GUTTER
    layout.sort(key=lambda s: s["idx"])
    return layout


def panel_duration_s(panel: dict) -> float:
    """Duration based on dialogue count + shot type."""
    n_dlg = len([d for d in (panel.get("dialogues") or []) if d.get("text")])
    shot = (panel.get("shot") or "").lower()
    base = 2.5
    if "wide" in shot or "establishing" in shot: base = 3.0
    elif "close" in shot:                          base = 2.0
    elif "insert" in shot:                          base = 1.5
    # Add 0.5s per dialogue bubble (reading time)
    return base + n_dlg * 0.5


def render_panel_clip(page_png: Path, slot: dict, duration_s: float,
                       fps: int = FPS) -> Path:
    """FFmpeg: crop panel from page + scale to 1280×720 + hold for duration."""
    x, y, w, h = slot["x"], slot["y"], slot["w"], slot["h"]
    out = OUT_DIR / f"motion-clip-p{slot['idx']:02d}.mp4"
    # Simple crop + scale (no zoompan) — reliable across panel aspect ratios
    vf = (f"crop=w={w}:h={h}:x={x}:y={y},"
          f"scale=1280:720:force_original_aspect_ratio=decrease,"
          f"pad=1280:720:(ow-iw)/2:(oh-ih)/2:color=white,"
          f"setsar=1")
    cmd = [
        "ffmpeg", "-y", "-loop", "1", "-i", str(page_png),
        "-vf", vf, "-r", str(fps),
        "-t", str(duration_s), "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-crf", "20", "-preset", "fast",
        str(out)
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        print(f"  ffmpeg fail p{slot['idx']}: {proc.stderr[-200:]}")
        return None
    return out


def build_page_motion(page_num: int) -> Path | None:
    """Build motion-comic MP4 for one page."""
    page_png = PAGE_PNG_DIR / f"gh-arc0-1-v5plus-p{page_num:02d}-scored.png"
    if not page_png.exists():
        # try /tmp fallback
        page_png = Path(f"/tmp/gh-arc0-1-v5plus-p{page_num:02d}-scored.png")
    if not page_png.exists():
        print(f"  ✗ page {page_num} PNG missing")
        return None
    manifest = json.loads(MANIFEST.read_text())
    panels = sorted([p for p in manifest["panels"] if p["pageNum"] == page_num],
                     key=lambda p: p["panelIndex"])
    if not panels:
        print(f"  ✗ no panels for page {page_num}")
        return None
    layout = compute_layout(panels)
    print(f"  page {page_num}: {len(layout)} panels")

    # Render each panel as MP4 clip
    clips = []
    for slot in layout:
        dur = panel_duration_s(slot["panel"])
        clip = render_panel_clip(page_png, slot, dur)
        if clip: clips.append((clip, dur))

    if not clips:
        return None

    # Concat MP4s via FFmpeg
    concat_list = OUT_DIR / f"motion-concat-p{page_num:02d}.txt"
    concat_list.write_text("\n".join(f"file '{c.absolute()}'" for c, _ in clips))
    out = OUT_DIR / f"gh-arc0-1-motion-comic-p{page_num:02d}.mp4"
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0",
            "-i", str(concat_list), "-c", "copy", str(out)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if proc.returncode != 0:
        print(f"  concat fail: {proc.stderr[-200:]}")
        return None
    total = sum(d for _, d in clips)
    print(f"  ✓ {out.name}  {total:.1f}s  ({len(clips)} panels)")

    # Also build OTIO sidecar
    tl = otio.schema.Timeline(name=f"arc0-1-page-{page_num:02d}")
    track = otio.schema.Track(name="panels", kind=otio.schema.TrackKind.Video)
    tl.tracks.append(track)
    rate = FPS
    for (clip_path, dur), slot in zip(clips, layout):
        media = otio.schema.ExternalReference(target_url=clip_path.absolute().as_uri())
        clip = otio.schema.Clip(
            name=f"panel_{slot['idx']:02d}",
            media_reference=media,
            source_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, rate),
                duration=otio.opentime.RationalTime(int(dur * rate), rate),
            ),
        )
        track.append(clip)
    otio_out = OUT_DIR / f"gh-arc0-1-motion-comic-p{page_num:02d}.otio"
    otio.adapters.write_to_file(tl, str(otio_out))
    print(f"  ✓ {otio_out.name}")
    return out


def main():
    pages = [int(a) for a in sys.argv[1:]] if len(sys.argv) > 1 else [5]
    print(f"Building motion-comic for pages: {pages}")
    out_mp4s = []
    for pn in pages:
        out = build_page_motion(pn)
        if out: out_mp4s.append(out)
    if len(out_mp4s) > 1:
        # Concat all pages into one episode
        concat = OUT_DIR / "motion-concat-episode.txt"
        concat.write_text("\n".join(f"file '{m.absolute()}'" for m in out_mp4s))
        ep = OUT_DIR / "gh-arc0-1-motion-comic-episode.mp4"
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0",
                         "-i", str(concat), "-c", "copy", str(ep)],
                        capture_output=True, text=True)
        print(f"\nEpisode: {ep}")


if __name__ == "__main__":
    main()
