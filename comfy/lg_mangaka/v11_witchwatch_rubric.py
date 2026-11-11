"""v11 Witch Watch rubric for Gemma vision QA.

Replaces the Death Note rubric (which over-rewards heavy ink + photo-real bg)
with a Witch Watch (Kenta Shinohara) rubric that values:
  - Clean readable line art
  - Expressive character faces (round eyes, emotion)
  - Light atmospheric screentone (NOT heavy chiaroscuro)
  - Dynamic but cheerful tone
  - Readable panel flow + dialogue integration

Used by jump_benchmark_qa when env V11_RUBRIC=witchwatch is set.
"""

WITCHWATCH_PROMPT = """\
You are evaluating a manga page against **Witch Watch** (篠原健太) — a
top-tier Weekly Shonen Jump publication. The art is CLEAN and expressive,
NOT heavy-ink dramatic like Death Note.

Calibration anchors (memorize these score points):
  10 = exactly Shinohara published page
   9 = AI-rendered but visually matches Witch Watch in this aspect
   7-8 = recognizable Jump manga, this aspect partly present
   5-6 = AI manga but this aspect is weak/inconsistent
   3-4 = wrong direction (e.g., heavy ink when it should be clean line)
   1-2 = AI artifact, aspect not present
   0  = unrecognizable / abstract

Witch Watch core qualities:
  - Clean thin pen line (NOT heavy black ink)
  - Light screentone, atmospheric (NOT deep chiaroscuro)
  - Round expressive eyes that show emotion
  - Atmospheric backgrounds (NOT photo-realistic detail)
  - Mid-tone palette (NOT stark black/white)
  - Round clean bubbles tightly integrated
  - Varied panel layout (bleed + tilt where action demands)
  - Cheerful / readable mood (NOT gritty)

Rate each axis 0-10. **Be generous when the image shows the intent**;
a clean AI-rendered manga panel that looks like Witch Watch deserves 8-9
even with minor imperfections. Reserve scores below 5 for genuine wrong
direction or missing aspect.

1. line_clarity (clean thin pen line):
   8-10 if lines look like manga pen (not photo-real, not blurry).
   3-5 if lines are heavy/inky like Death Note.
   0-2 if abstract noise / no readable lines.

2. character_expression (round expressive eyes + emotion):
   8-10 if you can read the character's mood from face.
   5-7 if face visible but expression neutral.
   0-3 if face missing or unreadable.

3. atmospheric_background (soft screentone, NOT photo-real):
   8-10 for Witch Watch-style soft scenery.
   3-5 for heavy photo-real detail or overdone bg.
   0-2 for empty white bg (when scene has setting).

4. panel_dynamism (varied panel sizes, bleed/tilt):
   8-10 if page has rhythm, asymmetric panels, bleed panels.
   5-7 if uniform grid but readable.
   0-3 if all panels identical rectangles.

5. bubble_integration (round clean bubbles, tightly placed):
   8-10 if bubbles in corners not covering subjects.
   5-7 if bubbles floating but readable.
   0-3 if bubbles cover faces / disrupt flow.

6. tonal_balance (mid-tone screentone, NOT extreme B&W):
   8-10 for Shinohara-tier balanced grays.
   3-5 for pure black + white (Death Note style).
   0-2 for washed gray-mud or stark monochrome.

7. sfx_text (hand-drawn SFX kana, well-placed):
   8-10 if SFX kana present + not covering character.
   5-7 if SFX present but small or odd placement.
   0-2 if no SFX (when action demands it).

8. readable_flow (clear reading order, no confusion):
   8-10 if R-to-L Jump flow works at a glance.
   5-7 if order requires thought.
   0-3 if panel order ambiguous.

Output EXACTLY this format. All 8 axes REQUIRED:
line_clarity: <N>
character_expression: <N>
atmospheric_background: <N>
panel_dynamism: <N>
bubble_integration: <N>
tonal_balance: <N>
sfx_text: <N>
readable_flow: <N>
overall_verdict: <one short sentence>
issues:
- <specific concrete problem>
- <specific concrete problem>
"""

WITCHWATCH_WEIGHTS = {
    "line_clarity":            0.15,
    "character_expression":    0.18,   # most important — Shinohara strength
    "atmospheric_background":  0.12,
    "panel_dynamism":          0.13,   # rewards bleed/tilt — our v11 C
    "bubble_integration":      0.10,
    "tonal_balance":           0.12,
    "sfx_text":                0.10,
    "readable_flow":           0.10,
}


def patch_jump_benchmark(jb_mod) -> None:
    """Monkey-patch jump_benchmark_qa to use Witch Watch rubric."""
    jb_mod.JUDGE_PROMPT = WITCHWATCH_PROMPT
    jb_mod.WEIGHTS = WITCHWATCH_WEIGHTS
