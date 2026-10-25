#!/usr/bin/env python3
"""Vision images for the README, generated with gemini-nano-banana-2.1 (16:9, 2K). No text, no logos."""
import base64
import pathlib
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from google import genai

OUT = pathlib.Path(__file__).resolve().parent.parent / "docs" / "images"
STYLE = " Soft cinematic lighting, high detail, clean composition, no text, no letters, no logos, no brand names."
PROMPTS = {
    "vision-sf-diorama": "Isometric 3D miniature diorama of the San Francisco waterfront on a floating square base: the Ferry Building with its clock tower in front, the Bay Bridge behind, a hill with a white tower, a red cable car on a street, piers and calm blue water. A glowing amber walking path with three small numbered round markers winds from the Ferry Building to nearby cafes.",
    "vision-quest-runner": "Stylized low-poly 3D game scene from behind: a runner jogging along a glowing pastel path that leads toward a tall white clock tower on a waterfront. Floating collectible tokens shaped like a coffee cup, a croissant and a star hover above the path. Soft sunrise sky, rounded trees, playful colors.",
    "vision-building-breakdown": "Isometric cutaway diorama of a long historic waterfront market hall with its roof removed, revealing the interior: a central nave with skylights, a bakery counter with pastries, a coffee bar with an espresso machine, cheese and produce stalls, small tables, warm lighting. Two stalls glow with a green outline ring and one with a red ring.",
    "vision-conference-gap": "Isometric 3D illustration of a bright conference venue floor with booths and a stage, and a person at the exit checking a phone that shows a small glowing map route leading out to a sunny street with a cafe. Pastel palette, friendly miniature people, clean and modern.",
    "vision-accessible-street": "Isometric illustration of a calm city street: wide sidewalks with tactile paving, a crosswalk, a wheelchair user and a companion, a person with a white cane, a parent with a child, cafe and bakery storefronts with soft green open glows, trees, clean vector style.",
    "vision-game-city": "Stylized 3D game world version of San Francisco at a pink and coral sunset: a waterfront clock tower building, a white hilltop tower, a red suspension bridge in the distance, colorful row houses on a hill, a winding purple road with a red cable car, palm trees and benches, toy-like and cheerful.",
}
client = genai.Client()


def make(name):
    t = time.perf_counter()
    it = client.interactions.create(model="gemini-nano-banana-2.1", input=PROMPTS[name] + STYLE,
                                    response_format={"type": "image", "mime_type": "image/jpeg", "aspect_ratio": "16:9", "image_size": "2K"})
    if not it.output_image:
        return f"{name}: no image ({it.status})"
    raw = OUT / f"{name}.raw.jpg"
    raw.write_bytes(base64.b64decode(it.output_image.data))
    subprocess.run(["sips", "-Z", "1600", "-s", "format", "jpeg", "-s", "formatOptions", "82", str(raw), "--out", str(OUT / f"{name}.jpg")], capture_output=True)
    raw.unlink(missing_ok=True)
    return f"{name}: {time.perf_counter() - t:.1f} s"


with ThreadPoolExecutor(6) as ex:
    for r in ex.map(lambda n: (lambda: make(n))() if True else None, sys.argv[1:] or list(PROMPTS)):
        print(r, flush=True)
