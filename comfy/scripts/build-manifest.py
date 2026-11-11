"""Generate /tmp/mangaka-gallery/manifest.json from img/ filesystem.

Single source of truth — gallery index.html fetches this and renders.
No HTML mutation, no nesting accumulation.
"""
import json, re, time
from pathlib import Path

IMG = Path("/tmp/mangaka-gallery/img")
OUT = Path("/tmp/mangaka-gallery/manifest.json")


def load_score(png_path):
    """If a sidecar JSON exists, return {total, label, scores, version, timings}."""
    j = png_path.with_name(png_path.name.replace("-scored.png", "-score.json"))
    if not j.exists(): return None
    try:
        d = json.loads(j.read_text())
        v = d.get("version", {})
        t = d.get("timings", {})
        # Build short version label (e.g. "v6+EEVEE" or "v5+CYCLES+LoRA+IPA")
        bits = []
        # first_axes preset / dominant axis lead the tag if present
        fa = v.get("first_axes") or {}
        if fa.get("preset"):
            bits.append(fa["preset"])
        elif fa.get("dominant"):
            bits.append(fa["dominant"][:3])
        base = v.get("v5_base", "?")
        if base == "v7":          bits.append("v7")
        elif base == "v6":        bits.append("v6")
        elif base == "cinematic": bits.append("CYC")
        elif base == "manga":     bits.append("MGA")
        else: bits.append(base)
        if v.get("use_lora"):     bits.append("LoRA")
        if v.get("use_ipadapter"): bits.append("IPA")
        if v.get("use_regional"): bits.append("RGN")
        if v.get("geonodes"):     bits.append("GN")
        if v.get("max_iter", 1) > 1:
            bits.append(f"x{v.get('max_iter')}")
        version_tag = "+".join(bits) if bits else None
        return {
            "total":   d.get("total"),
            "label":   d.get("jump_tier_label", ""),
            "scores":  d.get("scores", {}),
            "version": v,
            "version_tag": version_tag,
            "timings_total_s": t.get("total_pipeline_s"),
        }
    except Exception:
        return None


def categorize(name):
    if re.search(r"motion-comic.*\.mp4$", name):                return "motion_comic"
    # v8 color (Pony / Animagine color, JoJo color rubric)
    if name.startswith("v8-color-p") and "scored" in name:       return "v8_color"
    # kaizen iter snapshots
    if name.startswith("kaizen-p") and "scored" in name:         return "kaizen_iters"
    if "-v5plus-p" in name and "scored" in name:                 return "v5plus_final"
    if "v5-stylized-pg" in name and name.endswith("-bw.png"):    return "v5plus_panels"
    if "v5-stylized-pg" in name:                                  return None  # skip non-BW
    if "gh-arc0-1-v5-p" in name and "scored" in name:            return "v5_baseline"
    if "gh-arc0-1-v4-" in name:                                   return "v4"
    if name.endswith(".png"):                                     return "older"
    return None


def load_color_score(png_path):
    """Sidecar for v8 color (jump_color_qa shape)."""
    j = png_path.with_name(png_path.name.replace("-scored.png", "-score.json"))
    if not j.exists(): return None
    try:
        d = json.loads(j.read_text())
        return {
            "total":       d.get("total"),
            "label":       d.get("label", ""),
            "scores":      d.get("scores", {}),
            "verdict":     d.get("verdict", ""),
            "version":     d.get("version", {}),
            "version_tag": "v8+color",
        }
    except Exception:
        return None


def main():
    sections = {k: [] for k in ["v8_color","kaizen_iters","v5plus_final",
                                  "v5plus_panels","motion_comic",
                                  "v5_baseline","v4","older"]}
    files = list(IMG.glob("*"))
    for p in files:
        cat = categorize(p.name)
        if cat is None: continue
        item = {
            "file":  p.name,
            "mtime": int(p.stat().st_mtime),
            "size":  p.stat().st_size,
            "kind":  "video" if p.suffix == ".mp4" else "image",
        }
        if cat == "v8_color":
            item["score"] = load_color_score(p)
        elif cat in ("v5plus_final", "v5_baseline", "kaizen_iters"):
            item["score"] = load_score(p)
        sections[cat].append(item)

    # Sort each section newest first
    for k, v in sections.items():
        v.sort(key=lambda x: -x["mtime"])
    # Cap older to first 30 (keep page light)
    sections["older"] = sections["older"][:30]
    sections["v5plus_panels"] = sections["v5plus_panels"][:30]

    total = sum(len(v) for v in sections.values())
    OUT.write_text(json.dumps({
        "total": total,
        "generated_at": int(time.time()),
        "sections": sections,
    }, indent=2, ensure_ascii=False))
    print(f"OK: {OUT}  ({total} items)")


if __name__ == "__main__":
    main()
