"""OpenToonz xdts (exchange digital timesheet) export from manga manifest.

User: OpenToonz を活用してみて

xdts is OpenToonz's timesheet/xsheet exchange format (XML-based JSON
since v1.5). Each row = frame; columns = animation layers / panel slots.

For manga manifest:
  page → xsheet (rows = panels)
  each panel = 1 cell with image reference + duration + dialogue

Output is a .xdts file (JSON since OpenToonz 1.5) that can be imported
into OpenToonz Tab Browser for motion-comic compilation, ink+paint,
or timing adjustment.

Schema:
  {
    "fileType": "xdts",
    "fileVersion": "1.0",
    "fileRevision": "1",
    "metaData": {
      "title": "manga page N",
      "fps": 24,
      "frameCount": <sum of panel durations>,
      "timeTableHeaderTextList": ["Panel", "Image", "Dialogue"]
    },
    "timeTables": [
      {"timeTableId": 1,
       "fields": [
         {"fieldId": "Panel",      "fieldType": "TEXT"},
         {"fieldId": "Image",      "fieldType": "IMAGE_REFERENCE"},
         {"fieldId": "Dialogue",   "fieldType": "TEXT"},
       ],
       "frames": [
         {"frameNumber": N, "values": ["panel_idx", "img path", "dialogue"]},
         ...
       ]
      }
    ]
  }
"""
from __future__ import annotations
import json
from pathlib import Path

FPS = 24


def panel_duration_frames(panel: dict) -> int:
    """Frame count per panel based on shot type + dialogue."""
    n_dlg = len([d for d in (panel.get("dialogues") or []) if d.get("text")])
    shot = (panel.get("shot") or "").lower()
    base_s = 2.5
    if "wide" in shot or "establishing" in shot: base_s = 3.0
    elif "close" in shot:                          base_s = 2.0
    elif "insert" in shot:                          base_s = 1.5
    base_s += n_dlg * 0.5
    return int(base_s * FPS)


def export_page(panels: list, page_num: int, img_dir: Path,
                 out_path: Path) -> Path:
    panels_sorted = sorted(panels, key=lambda p: p["panelIndex"])
    frames = []
    cur_frame = 1
    for p in panels_sorted:
        idx = p["panelIndex"]
        dur = panel_duration_frames(p)
        dlg_text = " / ".join(d.get("text", "") for d in (p.get("dialogues") or [])[:2])
        img_path = str(img_dir / f"v5-stylized-pg{page_num:02d}-p{idx:02d}-bw.png")
        # One cell entry per frame (held for `dur` frames)
        frames.append({
            "frameNumber":     cur_frame,
            "frameCount":      dur,
            "panelIndex":      idx,
            "shot":            p.get("shot", "MS"),
            "tone":            p.get("tone", ""),
            "sceneSubject":    p.get("sceneSubject", "")[:200],
            "imageReference":  img_path,
            "dialogue":        dlg_text[:200],
            "characters":      p.get("focusedCharacters", []),
        })
        cur_frame += dur

    total_frames = cur_frame - 1
    xdts = {
        "fileType":     "xdts",
        "fileVersion":  "1.0",
        "fileRevision": "1",
        "metaData": {
            "title":      f"ghost hacker arc 0-1 page {page_num}",
            "fps":        FPS,
            "frameCount": total_frames,
            "timeTableHeaderTextList": ["Panel", "Shot", "Image", "Dialogue", "Characters"]
        },
        "timeTables": [{
            "timeTableId": 1,
            "fields": [
                {"fieldId": "Panel",         "fieldType": "TEXT"},
                {"fieldId": "Shot",          "fieldType": "TEXT"},
                {"fieldId": "Image",         "fieldType": "IMAGE_REFERENCE"},
                {"fieldId": "Dialogue",      "fieldType": "TEXT"},
                {"fieldId": "Characters",    "fieldType": "TEXT"},
            ],
            "frames": frames,
        }],
        # gftd extensions (non-standard, but OpenToonz ignores unknown fields)
        "_gftd_metadata": {
            "source":      "mangaka v5+ pipeline",
            "page_num":    page_num,
            "scene_slug":  panels_sorted[0].get("_scene_slug") if panels_sorted else None,
            "manifest_panel_count": len(panels_sorted),
        }
    }
    out_path.write_text(json.dumps(xdts, indent=2, ensure_ascii=False))
    return out_path


def export_episode(manifest_path: Path, out_dir: Path,
                    img_dir: Path) -> list[Path]:
    manifest = json.loads(manifest_path.read_text())
    pages = sorted(set(p["pageNum"] for p in manifest["panels"]))
    out_dir.mkdir(parents=True, exist_ok=True)
    outs = []
    for pn in pages:
        page_panels = [p for p in manifest["panels"] if p["pageNum"] == pn]
        out = out_dir / f"page-{pn:02d}.xdts"
        export_page(page_panels, pn, img_dir, out)
        outs.append(out)
        print(f"  ✓ {out.name}: {len(page_panels)} panels")
    return outs


if __name__ == "__main__":
    import sys
    page = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    MANIFEST = Path("/Users/junkawasaki/gftdcojp/ai-gftd-apps-gftdcojp/60-apps/ai-gftd-project-mangaka/data/ghosthacker/resources/episodes/arc0-1-origin/image-gen-manifest.json")
    img_dir = Path("/tmp")
    out_dir = Path("/tmp/mangaka-xdts")
    out_dir.mkdir(exist_ok=True)
    manifest = json.loads(MANIFEST.read_text())
    page_panels = [p for p in manifest["panels"] if p["pageNum"] == page]
    out = out_dir / f"page-{page:02d}.xdts"
    export_page(page_panels, page, img_dir, out)
    print(f"OK: {out}  ({len(page_panels)} panels)")
    # Show first frames
    data = json.loads(out.read_text())
    print(f"\nFirst 3 frames:")
    for f in data["timeTables"][0]["frames"][:3]:
        print(f"  frame {f['frameNumber']}: panel {f['panelIndex']} ({f['shot']}) "
              f"{f['frameCount']} frames")
