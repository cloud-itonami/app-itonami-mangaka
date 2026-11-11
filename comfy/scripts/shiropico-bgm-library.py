"""Generate a reusable SHIRO & PICO BGM library (numpy synth, loopable).

8 mood tracks (~40s each, seamless loop) so the episode builder picks a track by
mood instead of synthesising BGM every render. Cyber-anime palette: square/saw
leads, sine pads, kick/snare/hat drums, per-mood chord progression & tempo.

Out: resources/bgm/{action,daily,mystery,comedy,emotional,tension,victory,codex}.wav
"""
from __future__ import annotations
import wave
from pathlib import Path
import numpy as np

OUT = Path(__file__).resolve().parents[2] / "data/ghosthacker-shiropico/resources/bgm"
OUT.mkdir(parents=True, exist_ok=True)
SR = 44100
N = {  # note → Hz
    "C2": 65.41, "D2": 73.42, "E2": 82.41, "F2": 87.31, "G2": 98.0, "A2": 110.0, "B2": 123.47,
    "C3": 130.81, "D3": 146.83, "E3": 164.81, "F3": 174.61, "G3": 196.0, "A3": 220.0, "B3": 246.94,
    "C4": 261.63, "D4": 293.66, "E4": 329.63, "F4": 349.23, "G4": 392.0, "A4": 440.0, "B4": 493.88,
    "C5": 523.25, "D5": 587.33, "E5": 659.25, "F5": 698.46, "G5": 783.99, "A5": 880.0, "Bb4": 466.16,
    "Eb4": 311.13, "Ab4": 415.30, "Bb3": 233.08, "Eb3": 155.56, "F#4": 369.99, "C#4": 277.18,
}

def env(n, a=0.01, d=0.06, s=0.7, r=0.1):
    e = np.ones(n); ai, di, ri = int(a*SR), int(d*SR), int(r*SR)
    if ai: e[:ai] = np.linspace(0, 1, ai)
    if di: e[ai:ai+di] = np.linspace(1, s, di)
    e[ai+di:max(ai+di, n-ri)] = s
    if ri: e[n-ri:] = np.linspace(s, 0, ri)
    return e

def osc(freq, dur, kind="saw", vol=0.3, **kw):
    n = int(dur*SR); t = np.arange(n)/SR
    if kind == "saw": w = 2*(t*freq - np.floor(0.5+t*freq))
    elif kind == "square": w = np.sign(np.sin(2*np.pi*freq*t))
    elif kind == "tri": w = 2*np.abs(2*(t*freq-np.floor(t*freq+0.5)))-1
    else: w = np.sin(2*np.pi*freq*t)
    return (w*env(n, **kw)*vol).astype(np.float32)

def kick(d=0.2):
    n = int(d*SR); t = np.arange(n)/SR
    return (np.sin(2*np.pi*(150*np.exp(-t*30)+45)*t)*np.exp(-t*9)*0.95).astype(np.float32)
def snare(d=0.16):
    n = int(d*SR); t = np.arange(n)/SR
    return ((np.random.randn(n)*0.6+np.sin(2*np.pi*200*t)*0.3)*np.exp(-t*18)*0.55).astype(np.float32)
def hat(d=0.05, v=0.18):
    n = int(d*SR); return (np.random.randn(n)*np.exp(-np.arange(n)/SR*90)*v).astype(np.float32)


def track(prog, lead, bpm, bars, kind_lead="saw", drums="full", pad=True, lead_oct=1.0, mood_vol=1.0):
    beat = 60/bpm; bar = beat*4; total = bar*bars
    n = int(total*SR); mix = np.zeros(n, np.float32)
    def put(sig, at, g=1.0):
        i = int(at*SR); e = min(n, i+len(sig)); mix[i:e] += sig[:e-i]*g
    for b in range(bars):
        t0 = b*bar; ch = prog[b % len(prog)]
        if drums in ("full", "soft"):
            for k in range(4):
                put(kick(), t0+k*beat, 1.0 if drums == "full" else 0.6)
                put(hat(v=0.18 if drums == "full" else 0.1), t0+k*beat+beat/2)
                if k in (1, 3) and drums == "full": put(snare(), t0+k*beat)
        # bass
        put(osc(N[ch[0]], bar, "square", 0.22, s=0.85, r=0.05), t0)
        # pad
        if pad:
            for nt in ch[1:]:
                put(osc(N[nt], bar, "sine", 0.09, a=0.05, s=0.9, r=0.2), t0)
        # lead
        mt = t0
        for nm, bts in lead[b % len(lead)]:
            if nm:
                f = N[nm]*lead_oct
                put(osc(f, beat*bts*0.92, kind_lead, 0.20, a=0.01, d=0.03, s=0.85, r=0.04), mt)
            mt += beat*bts
    mix = np.tanh(mix*1.05)*0.9*mood_vol
    # seamless-ish loop: tiny crossfade tail→head
    xf = int(0.05*SR)
    mix[:xf] = mix[:xf]*np.linspace(0, 1, xf) + mix[-xf:]*np.linspace(1, 0, xf)
    return mix[:n-xf]


def save(name, sig):
    p = OUT / f"{name}.wav"
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(sig, -1, 1)*32767).astype(np.int16).tobytes())
    print(f"  {name}.wav ({len(sig)/SR:.0f}s)")


def main():
    L = lambda *xs: list(xs)
    # 1 ACTION — driving minor, fast
    save("action", track(
        [("A2", "C4", "E4"), ("F2", "A3", "C4"), ("C3", "E4", "G4"), ("G2", "B3", "D4")],
        [L(("E5", 1), ("C5", .5), ("D5", .5), ("E5", 1), ("A4", 1)), L(("F4", 1), ("E4", 1), ("C4", 2)),
         L(("E4", 1), ("G4", .5), ("E4", .5), ("C4", 1), ("G3", 1)), L(("A4", 2), ("G4", 1), ("E4", 1))],
        bpm=158, bars=16, kind_lead="saw"))
    # 2 DAILY — light major, mid
    save("daily", track(
        [("C3", "E4", "G4"), ("A2", "C4", "E4"), ("F2", "A3", "C4"), ("G2", "B3", "D4")],
        [L(("E4", 1), ("G4", 1), ("C5", 2)), L(("C4", 1), ("E4", 1), ("A4", 2)),
         L(("A3", 1), ("C4", 1), ("F4", 2)), L(("B3", 1), ("D4", 1), ("G4", 2))],
        bpm=104, bars=16, kind_lead="tri", drums="soft"))
    # 3 MYSTERY — ominous minor, slow, ambient (no drums)
    save("mystery", track(
        [("D2", "F3", "A3"), ("Bb3", "D3", "F3"), ("C3", "Eb3", "G3"), ("A2", "C4", "E4")],
        [L(("D4", 2), ("F4", 2)), L(("Eb4", 2), ("D4", 2)), L(("C4", 2), ("Bb3", 2)), L(("A3", 4))],
        bpm=78, bars=12, kind_lead="sine", drums="none", lead_oct=1.0))
    # 4 COMEDY — bouncy, playful, staccato
    save("comedy", track(
        [("C3", "E4", "G4"), ("G2", "B3", "D4"), ("A2", "C4", "E4"), ("F2", "A3", "C4")],
        [L(("C5", .5), ("E5", .5), ("G4", .5), ("C5", .5), ("E5", 1), (None, 1)),
         L(("D5", .5), ("B4", .5), ("G4", .5), ("D5", .5), ("B4", 1), (None, 1)),
         L(("E5", .5), ("C5", .5), ("A4", .5), ("E5", .5), ("C5", 1), (None, 1)),
         L(("F4", .5), ("A4", .5), ("C5", .5), ("F4", .5), ("A4", 1), (None, 1))],
        bpm=140, bars=16, kind_lead="square"))
    # 5 EMOTIONAL — gentle, warm, slow
    save("emotional", track(
        [("C3", "E4", "G4"), ("A2", "C4", "E4"), ("F2", "A3", "C4"), ("G2", "B3", "D4")],
        [L(("G4", 2), ("E4", 2)), L(("E4", 2), ("C4", 2)), L(("F4", 2), ("A4", 2)), L(("D4", 2), ("G4", 2))],
        bpm=72, bars=12, kind_lead="sine", drums="soft", mood_vol=0.9))
    # 6 TENSION — suspense pulse, minor
    save("tension", track(
        [("E2", "G3", "B3"), ("E2", "G3", "B3"), ("C3", "E3", "G3"), ("D3", "F#4", "A3")],
        [L(("B3", .5), (None, .5), ("B3", .5), (None, .5), ("E4", 2)),
         L(("B3", .5), (None, .5), ("C4", .5), (None, .5), ("E4", 2)),
         L((None, 4)), L(("D4", 1), ("E4", 1), ("F#4", 2))],
        bpm=128, bars=14, kind_lead="saw", drums="soft"))
    # 7 VICTORY — triumphant major, bright
    save("victory", track(
        [("C3", "E4", "G4"), ("G2", "B3", "D4"), ("A2", "C4", "E4"), ("F2", "A3", "C4")],
        [L(("C5", 1), ("E5", 1), ("G5", 2)), L(("G4", 1), ("D5", 1), ("B4", 2)),
         L(("A4", 1), ("E5", 1), ("C5", 2)), L(("F4", 1), ("A4", 1), ("C5", 2))],
        bpm=150, bars=14, kind_lead="saw"))
    # 8 CODEX — light educational, clean
    save("codex", track(
        [("C3", "E4", "G4"), ("F2", "A3", "C4"), ("G2", "B3", "D4"), ("C3", "E4", "G4")],
        [L(("E4", 1), ("F4", 1), ("G4", 1), ("E4", 1)), L(("F4", 1), ("G4", 1), ("A4", 2)),
         L(("G4", 1), ("A4", 1), ("B4", 2)), L(("C5", 2), ("G4", 2))],
        bpm=112, bars=12, kind_lead="tri", drums="soft"))
    print("BGM library DONE →", OUT)


if __name__ == "__main__":
    main()
