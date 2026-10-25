#!/usr/bin/env python3
"""Headset-lens overlay for the POV edit: black frame, two soft circular lenses, HUD text. Writes a PNG."""
import sys
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H, R = 1920, 1080, 470
CENTERS = [(W // 4 + 10, H // 2), (3 * W // 4 - 10, H // 2)]
out = sys.argv[1] if len(sys.argv) > 1 else "lens_overlay.png"
mask = Image.new("L", (W, H), 0)
d = ImageDraw.Draw(mask)
for cx, cy in CENTERS:
    d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=255)
mask = mask.filter(ImageFilter.GaussianBlur(22))
overlay = Image.new("RGBA", (W, H), (0, 0, 0, 255))
overlay.putalpha(Image.eval(mask, lambda a: 255 - a))  # opaque black outside the lenses
hud = ImageDraw.Draw(overlay)
font = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 30)
small = ImageFont.truetype("/System/Library/Fonts/Supplemental/Arial Bold.ttf", 22)
for i, (cx, cy) in enumerate(CENTERS):
    hud.text((cx - 150, cy - R + 70), "CITYQUEST  SIM", font=font, fill=(77, 163, 255, 255))
    hud.ellipse([cx + 160, cy - R + 78, cx + 176, cy - R + 94], fill=(255, 77, 77, 255))
    hud.text((cx + 184, cy - R + 74), "LIVE", font=small, fill=(255, 77, 77, 255))
    hud.text((cx - 190, cy + R - 110), "gemini-3.8-live sees the street", font=small, fill=(244, 237, 225, 230))
overlay.save(out)
print("wrote", out)
