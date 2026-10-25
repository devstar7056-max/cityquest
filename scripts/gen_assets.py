#!/usr/bin/env python3
"""Generate CityQuest assets once, never at demo time. Needs GEMINI_API_KEY.

  sprites  gemini-nano-banana-2.1: the 15 reward sprites in schema/quest.schema.json -> web/sprites/*.png
  loop     lyria-3-clip-preview: one 30 s background loop -> web/audio/loop.mp3
  lore     deep-research-preview-04-2026: a cited line on what each merchant sells -> data/lore.json

Usage: python3 scripts/gen_assets.py [sprites] [loop] [lore]   (default: all three)
"""
import base64
import json
import pathlib
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor

from google import genai

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPRITES = ROOT / "web" / "sprites"
AUDIO = ROOT / "web" / "audio"
LORE = ROOT / "data" / "lore.json"
SCHEMA = json.loads((ROOT / "schema" / "quest.schema.json").read_text())
NAMES = SCHEMA["$defs"]["stop"]["properties"]["reward"]["properties"]["sprite"]["enum"]
THINGS = {"coffee": "a steaming coffee cup", "tea": "a teacup with a tea leaf", "icecream": "an ice cream cone",
          "chocolate": "a chocolate bar with one square broken off", "pastry": "a flaky croissant",
          "bread": "a round sourdough loaf", "oyster": "an open oyster shell with a pearl",
          "book": "an open book", "ceramics": "a handmade ceramic vase", "clocktower": "a white clock tower",
          "pier": "a wooden pier over blue water", "ferry": "a small ferry boat", "wine": "a glass of red wine",
          "beer": "a frothy pint of beer", "star": "a golden star"}
STYLE = ("A single collectible game token for a city exploration game: {thing}. Round glossy coin badge, "
         "bold simple shapes, warm palette of cream, terracotta and San Francisco bay blue, soft rim light, "
         "centered, fills the frame, flat solid cream background (#F4EDE1), no text, no letters.")

client = genai.Client()


def log(msg):
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def sprite(name):
    out = SPRITES / f"{name}.png"
    if out.exists():
        return f"{name}: exists"
    t = time.perf_counter()
    it = client.interactions.create(model="gemini-nano-banana-2.1", input=STYLE.format(thing=THINGS[name]))
    if not it.output_image:
        return f"{name}: no image ({it.status})"
    raw = SPRITES / f"{name}.full.png"
    raw.write_bytes(base64.b64decode(it.output_image.data))
    subprocess.run(["sips", "-Z", "192", "-s", "format", "png", str(raw), "--out", str(out)],
                   capture_output=True, check=False)
    raw.unlink(missing_ok=True)
    return f"{name}: {time.perf_counter() - t:.1f} s"


def sprites():
    SPRITES.mkdir(parents=True, exist_ok=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        for line in ex.map(lambda n: _safe(sprite, n), NAMES):
            log(f"sprite {line}")


def loop():
    AUDIO.mkdir(parents=True, exist_ok=True)
    t = time.perf_counter()
    it = client.interactions.create(
        model="lyria-3-clip-preview",
        input=("Light, playful instrumental loop for a city exploration game set at the San Francisco "
               "Ferry Building on a sunny afternoon. Plucked guitar, soft marimba, brushed drums, gentle "
               "bay breeze feel, 100 BPM, seamless loop, no vocals."))
    if not it.output_audio:
        log(f"loop: no audio ({it.status})")
        return
    ext = "wav" if "wav" in (it.output_audio.mime_type or "") else "mp3"
    (AUDIO / f"loop.{ext}").write_bytes(base64.b64decode(it.output_audio.data))
    log(f"loop: {time.perf_counter() - t:.1f} s -> web/audio/loop.{ext} ({it.output_audio.mime_type})")


def lore():
    seed = json.loads((ROOT / "data" / "merchants.seed.json").read_text())
    rows = [f"- key={p['key']} | {p['name']} | unit {p.get('unit')} | {p.get('category')}"
            for p in seed["places"] if p.get("kind") == "merchant"]
    prompt = ("Research the merchants of the Ferry Building Marketplace in San Francisco listed below. For each "
              "one, find what it sells or serves, in at most 12 words, from the merchant's own site, the "
              "Ferry Building Marketplace site, or a reputable outlet, and whether it was founded in San "
              "Francisco or the Bay Area. If you cannot confirm a fact, use null. Never guess.\n\n"
              + "\n".join(rows) +
              "\n\nEnd your report with one fenced ```json block: a list of objects "
              '{"key": ..., "what": ..., "local": "SF" | "Bay Area" | null, "source_url": ...}, one per merchant.')
    t = time.perf_counter()
    it = client.interactions.create(agent="deep-research-preview-04-2026", input=prompt, background=True)
    log(f"lore: deep research started {it.id[:16]}...")
    while it.status in ("in_progress", "queued"):
        time.sleep(15)
        it = client.interactions.get(id=it.id)
    text = it.output_text or ""
    (ROOT / "data" / "lore.report.md").write_text(text)
    m = re.findall(r"```json\s*(.*?)```", text, re.S)
    items = []
    if m:
        try:
            items = json.loads(m[-1])
        except json.JSONDecodeError as e:
            log(f"lore: JSON block did not parse: {e}")
    LORE.write_text(json.dumps({"agent": "deep-research-preview-04-2026", "interaction_id": it.id,
                                "generated_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "status": it.status,
                                "items": items}, indent=2))
    log(f"lore: {it.status} in {time.perf_counter() - t:.0f} s, {len(items)} merchants -> data/lore.json")


def _safe(fn, *a):
    try:
        return fn(*a)
    except Exception as e:
        return f"{a[0] if a else fn.__name__}: ERROR {type(e).__name__}: {str(e)[:200]}"


if __name__ == "__main__":
    jobs = sys.argv[1:] or ["sprites", "loop", "lore"]
    with ThreadPoolExecutor(max_workers=3) as ex:
        futs = [ex.submit(_safe, {"sprites": sprites, "loop": loop, "lore": lore}[j]) for j in jobs]
        for f in futs:
            r = f.result()
            if r:
                log(str(r))
