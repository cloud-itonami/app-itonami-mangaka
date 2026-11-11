"""OpenTimelineIO motion-comic assembler.

Takes the per-page PNG outputs from `mangaka_compose_page_v4` and
assembles them into an OTIO timeline ready for FFmpeg encode into
a motion-comic MP4. Each page is held for N seconds, with optional
panel-to-panel pan/zoom (Ken Burns) effect computed from the panel
layout.

Usage:
    python otio_motion_comic.py \
      --pages /tmp/gh-arc0-1-v4-p00.png /tmp/gh-arc0-1-v4-p01.png ... \
      --page-duration 4.0 \
      --transition 0.5 \
      --out /tmp/gh-arc0-1-motion-comic.otio

Then encode:
    otioconvert -i out.otio -o out.fcpxml   # for Final Cut import
    OR
    ffmpeg-from-otio out.otio out.mp4       # direct render

OpenTimelineIO is timeline metadata only — actual media is referenced
via ExternalReference. FFmpeg / other tools materialise the video.
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path

try:
    import opentimelineio as otio
    OTIO_AVAILABLE = True
except ImportError:
    OTIO_AVAILABLE = False


def assemble(
    page_paths: list[Path],
    page_duration_s: float = 4.0,
    transition_s: float = 0.5,
    fps: int = 24,
) -> "otio.schema.Timeline":
    """Build a single-track timeline from page PNGs.

    Per page:
      - hold the static image for `page_duration_s` seconds
      - cross-dissolve `transition_s` to the next

    Future: read per-page sidecar JSON for panel layouts + add Ken
    Burns motion (pan/zoom) per panel within a page.
    """
    if not OTIO_AVAILABLE:
        raise RuntimeError("opentimelineio not installed — `pip install opentimelineio`")

    tl = otio.schema.Timeline(name="ghost-hacker-arc01-motion-comic")
    track = otio.schema.Track(name="page_video", kind=otio.schema.TrackKind.Video)
    tl.tracks.append(track)

    rate = fps
    hold_frames = int(page_duration_s * rate)
    trans_frames = int(transition_s * rate)

    for i, path in enumerate(page_paths):
        media = otio.schema.ExternalReference(
            target_url=path.absolute().as_uri(),
        )
        # Image is held for hold_frames + extra trans_frames for the
        # cross-dissolve on either side.
        total_frames = hold_frames + (trans_frames if i > 0 else 0) + (
            trans_frames if i < len(page_paths) - 1 else 0
        )
        clip = otio.schema.Clip(
            name=f"page_{i:02d}",
            media_reference=media,
            source_range=otio.opentime.TimeRange(
                start_time=otio.opentime.RationalTime(0, rate),
                duration=otio.opentime.RationalTime(total_frames, rate),
            ),
        )
        track.append(clip)
        # Add cross-dissolve to next page
        if i < len(page_paths) - 1:
            transition = otio.schema.Transition(
                name=f"dissolve_{i:02d}",
                transition_type=otio.schema.TransitionTypes.SMPTE_Dissolve,
                in_offset=otio.opentime.RationalTime(trans_frames, rate),
                out_offset=otio.opentime.RationalTime(trans_frames, rate),
            )
            track.append(transition)

    return tl


def main():
    if not OTIO_AVAILABLE:
        print("opentimelineio not installed — `pip install opentimelineio`")
        return 1

    parser = argparse.ArgumentParser()
    parser.add_argument("--pages", nargs="+", required=True, type=Path,
                          help="page PNG paths in order")
    parser.add_argument("--page-duration", type=float, default=4.0,
                          help="seconds each page is held")
    parser.add_argument("--transition", type=float, default=0.5,
                          help="seconds of cross-dissolve between pages")
    parser.add_argument("--fps", type=int, default=24)
    parser.add_argument("--out", type=Path, required=True,
                          help="output .otio file")
    args = parser.parse_args()

    tl = assemble(args.pages, args.page_duration, args.transition, args.fps)
    otio.adapters.write_to_file(tl, str(args.out))
    print(f"OK otio: {args.out}  ({len(args.pages)} pages, "
          f"{args.page_duration * len(args.pages):.1f}s + transitions)")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
