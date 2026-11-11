#!/usr/bin/env python3
"""Fleet resource pre-flight — visualize gad + murakumo fleet before any job.

Probes every Tailscale peer for the two services the manga pipeline uses:
  • ComfyUI  (:8188)  — RAM, VRAM free/total, queue depth
  • Ollama   (:11434) — currently loaded models + VRAM (busy vs idle)

Prints a table and a capacity verdict per GPU node so you can pick a node (or
wait) BEFORE submitting renders / co-scientist runs / LLM scoring. No deps
beyond httpx; reads the node list from `tailscale status`.

Usage:
  python scripts/fleet_status.py            # full fleet
  python scripts/fleet_status.py gad asher  # only named nodes
"""
from __future__ import annotations
import asyncio, subprocess, sys
import httpx

COMFY_PORT, OLLAMA_PORT = 8188, 11434
GB = 1024 ** 3


def peers() -> list[tuple[str, str]]:
    """[(name, ip)] from `tailscale status` (self included)."""
    for cmd in (["tailscale", "status"], ["/Applications/Tailscale.app/Contents/MacOS/Tailscale", "status"]):
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=10).stdout
            break
        except Exception:
            out = ""
    res = []
    for line in out.splitlines():
        p = line.split()
        if len(p) >= 2 and p[0].count(".") == 3:
            res.append((p[1], p[0]))  # (name, ip)
    return res


async def _get(client: httpx.AsyncClient, url: str):
    try:
        r = await client.get(url, timeout=4.0)
        return r.json() if r.status_code == 200 else None
    except Exception:
        return None


async def probe(name: str, ip: str) -> dict:
    info: dict = {"name": name, "ip": ip}
    async with httpx.AsyncClient() as c:
        stats, queue, ps = await asyncio.gather(
            _get(c, f"http://{ip}:{COMFY_PORT}/system_stats"),
            _get(c, f"http://{ip}:{COMFY_PORT}/queue"),
            _get(c, f"http://{ip}:{OLLAMA_PORT}/api/ps"),
        )
    if stats:
        s = stats.get("system", {})
        devs = stats.get("devices", [])
        d0 = devs[0] if devs else {}
        info["comfy"] = {
            "ram_free": s.get("ram_free", 0) // GB, "ram_total": s.get("ram_total", 0) // GB,
            "vram_free": d0.get("vram_free", 0) // GB, "vram_total": d0.get("vram_total", 0) // GB,
            "gpu": (d0.get("name", "") or "")[:22],
            "q_run": len((queue or {}).get("queue_running", [])),
            "q_pend": len((queue or {}).get("queue_pending", [])),
        }
    if ps is not None:
        ms = ps.get("models", [])
        info["ollama"] = [f"{m['name']}({m.get('size_vram',0)//GB}G)" for m in ms] if ms else []
    return info


def is_unified(gpu: str) -> bool:
    """APU / Apple Silicon — VRAM is carved from system RAM (unified memory)."""
    g = (gpu or "").lower()
    return ("mps" in g or "radeon" in g or "apu" in g or "integrated" in g
            or "8060s" in g or "strix" in g)


def verdict(c: dict) -> str:
    # SDXL needs ~6-8 GB. On unified-memory nodes (APU/Apple) the GPU draws from
    # system RAM via GTT, so the real ceiling is FREE SYSTEM RAM, not the BIOS
    # VRAM carve-out — a node can show free VRAM yet be swapping. Gate on both.
    if c["q_run"] or c["q_pend"]:
        return f"BUSY (q {c['q_run']}+{c['q_pend']})"
    unified = is_unified(c.get("gpu", ""))
    if unified and c["ram_free"] < 6:
        return "PRESSURED (swap)"
    eff = min(c["vram_free"], c["ram_free"]) if unified else c["vram_free"]
    if eff >= 8:
        return "FREE"
    if eff >= 5:
        return "OK (1 job)"
    return "LOW MEM"


async def main():
    want = set(a.lower() for a in sys.argv[1:])
    nodes = [(n, ip) for n, ip in peers() if not want or n.lower() in want]
    if not nodes:
        print("no matching tailscale peers"); return
    results = await asyncio.gather(*[probe(n, ip) for n, ip in nodes])
    print(f"\n{'NODE':<10}{'COMFYUI  VRAM free / RAM free / queue':<46}{'OLLAMA':<24}VERDICT")
    print("-" * 100)
    for r in sorted(results, key=lambda x: x["name"]):
        comfy = r.get("comfy")
        if comfy:
            tag = " ·unified" if is_unified(comfy.get("gpu", "")) else ""
            cstr = (f"VRAM {comfy['vram_free']}/{comfy['vram_total']}G  "
                    f"RAM {comfy['ram_free']}/{comfy['ram_total']}G  "
                    f"q={comfy['q_run']}r+{comfy['q_pend']}p{tag}")
            verd = verdict(comfy)
        else:
            cstr, verd = "—", ""
        oll = r.get("ollama")
        ostr = ("idle" if oll == [] else ", ".join(oll)) if oll is not None else "—"
        print(f"{r['name']:<10}{cstr:<46}{ostr:<24}{verd}")
    print("\nlegend: ComfyUI :8188, Ollama :11434. '·unified'=APU/Apple (GPU shares")
    print("system RAM via GTT — real ceiling is FREE RAM, not the VRAM carve-out).")
    print("Pick FREE; avoid BUSY/PRESSURED. Raise dedicated VRAM via BIOS UMA on APUs.\n")


if __name__ == "__main__":
    asyncio.run(main())
