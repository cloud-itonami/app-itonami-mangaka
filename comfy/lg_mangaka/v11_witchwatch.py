"""v11 A — Witch Watch art style profile.

Replaces the Death Note-heavy ink style with Kenta Shinohara's softer,
cleaner Witch Watch aesthetic:
  - Thin clean pen line (not sharp heavy ink)
  - Light screentone (not heavy chiaroscuro)
  - Expressive round eyes (not photo-real anatomy)
  - Soft / cheerful (not gritty / dramatic)
  - Backgrounds more atmospheric, less photo-real detail

Triggered by env V11_STYLE=witchwatch (default off = Death Note v10).
"""

QUALITY_INK = (
    "high-quality manga panel, thin clean pen line, light screentone, "
    "monochrome with soft mid-tones, expressive eyes, gentle atmosphere, "
)
QUALITY_COLOR = (
    "masterpiece, best quality, very aesthetic, "
    "soft anime illustration, gentle mood, "
)

NEG_INK = (
    "low quality, blurry, deformed, multiple people, twin, multiple faces, "
    "color, watercolor, photograph, "
    "heavy ink, heavy shadows, dramatic chiaroscuro, gritty, dark, "
    "Death Note style, photorealistic detail, harsh contrast"
)
NEG_COLOR = (
    "lowres, bad anatomy, bad hands, blurry, watermark, signature, "
    "2girls, 2boys, twin, group, "
    "heavy shadows, dark mood, gritty texture, oversaturated"
)

# Scene prompts re-tuned: lighter, more atmospheric, less photo-real
SCENE_INK = {
    "yuto-bedroom": (
        "Japanese teen bedroom interior, single bed, study desk with smartphone, "
        "punk band posters and concert tickets on wall, light evening window, "
        "wood floor, atmospheric soft screentone background, "
        "Witch Watch style by Kenta Shinohara"
    ),
    "classroom": (
        "Japanese high school classroom 3-B interior, rows of wooden desks, "
        "chalkboard with light writing, west window with daylight, "
        "school bags on chairs, light screentone walls, "
        "Witch Watch style by Kenta Shinohara"
    ),
    "school-hierarchy": (
        "Japanese high school classroom interior, wooden desks in rows, "
        "chalkboard, west window with afternoon sunlight, "
        "polished floor, atmospheric soft screentone, "
        "Witch Watch style by Kenta Shinohara"
    ),
    "rens-room": (
        "teen bedroom with multi-monitor wall showing code, gaming chair, "
        "research corkboard with photos, soft purple ambient light, "
        "atmospheric screentone, "
        "Witch Watch style by Kenta Shinohara"
    ),
    "neis-room": (
        "teen girl bedroom interior, vanity mirror, wardrobe, single bed, "
        "K-pop concert posters, large window with morning sunlight, "
        "soft light screentone, "
        "Witch Watch style by Kenta Shinohara"
    ),
    "city-street": (
        "Japanese residential neighborhood street, sidewalk, low wall, "
        "two-storey wooden houses, telephone poles, vending machine, "
        "bicycle leaning, soft golden hour, "
        "atmospheric screentone, "
        "Witch Watch style by Kenta Shinohara"
    ),
}

# Color scene prompts (used when pipeline=cu_color / cu_color_usd)
SCENE_COLOR = {
    "yuto-bedroom":     "japanese teen bedroom, single bed, study desk, punk posters, soft evening warm light",
    "classroom":        "japanese high school classroom, wooden desks, chalkboard, west window, afternoon sunlight",
    "school-hierarchy": "japanese high school classroom, desks, chalkboard, large window, afternoon light",
    "rens-room":        "teen bedroom, multi-monitor, gaming chair, soft purple ambient",
    "neis-room":        "teen girl bedroom, vanity, wardrobe, posters, morning sunlight",
    "city-street":      "japanese residential street, sidewalk, houses, golden hour",
}

# Character descriptions — emphasize expressive features, not photo-real
CHAR_INK = {
    "Yuto":  "1boy, 17yo japanese teen, messy black hair, expressive dark eyes, "
              "white school shirt, navy slacks, slim build, friendly clean style",
    "Ren":   "1boy, 17yo japanese teen, dark hair under hoodie, droopy expressive eyes, "
              "oversized grey hoodie, slouchy charming pose, clean style",
    "Nei":   "1girl, 16yo japanese teen, long platinum blonde hair, large blue eyes, "
              "navy sailor uniform with red ribbon, gentle expression, clean style",
    "Akira": "1boy, 17yo japanese teen, short brown hair, mischievous round eyes, "
              "fashionable streetwear, playful pose, clean style",
    "Saki":  "1girl, 16yo japanese teen, shoulder-length brown bob, large skeptical eyes, "
              "navy sailor uniform, deadpan expression, clean style",
}
CHAR_COLOR = CHAR_INK   # same descriptions; color/ink differ only by prompt prefix


def patch_module(target_mod) -> None:
    """Monkey-patch the target v10_panel_render module with Witch Watch
    constants. Idempotent."""
    target_mod.QUALITY_INK = QUALITY_INK
    target_mod.QUALITY_COLOR = QUALITY_COLOR
    target_mod.NEG_INK = NEG_INK
    target_mod.NEG_COLOR = NEG_COLOR
    target_mod.SCENE_INK = SCENE_INK
    target_mod.SCENE_COLOR = SCENE_COLOR
    target_mod.CHAR_INK = CHAR_INK
    target_mod.CHAR_COLOR = CHAR_COLOR


def get_ink_footer() -> str:
    """Footer added at end of ink prompt (replaces 'Death Note ink style')."""
    return "Witch Watch style by Kenta Shinohara, professional manga"
