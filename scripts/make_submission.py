#!/usr/bin/env python3
"""Assemble the submission video (1920x1080, about 70 s) from real pieces:
title card, the Higgsfield-expanded jog (muted), the Seedance sim-style redo, real sim recordings,
captions drawn with Pillow, and the Lyria loop as the soundtrack.

Usage: python3 scripts/make_submission.py --title T.png --jog JOG16x9.mp4 --redo REDO.mp4 --sim SIM.webm [--sim2 SIM2.webm]
       [--music web/audio/loop.mp3] --out media/out/cityquest_submission.mp4
"""
import argparse
import pathlib
import subprocess
import tempfile

from PIL import Image, ImageDraw, ImageFont

W, H = 1920, 1080
FONT = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def caption_png(text, path, sub=None):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    f = ImageFont.truetype(FONT, 54)
    fs = ImageFont.truetype(FONT, 32)
    tw = d.textlength(text, font=f)
    sw = d.textlength(sub, font=fs) if sub else 0
    bw = max(tw, sw) + 80
    bh = 110 + (52 if sub else 0)
    x0, y0 = (W - bw) / 2, H - bh - 60
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=22, fill=(8, 12, 20, 205))
    d.text(((W - tw) / 2, y0 + 26), text, font=f, fill=(244, 237, 225, 255))
    if sub:
        d.text(((W - sw) / 2, y0 + 96), sub, font=fs, fill=(77, 163, 255, 255))
    img.save(path)


def run(args):
    print("+", " ".join(str(a) for a in args)[:240])
    subprocess.run(args, check=True)


def fit(src, out, start, dur, speed=1.0, cap=None, blur_bg=True):
    """Scale any clip into 1920x1080 (blurred fill for portrait), trim, optional caption, no audio."""
    vf = (f"[0:v]trim={start}:{start + dur * speed},setpts=(PTS-STARTPTS)/{speed},fps=30,split[a][b];"
          f"[a]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},boxblur=30:2,eq=brightness=-0.12[bg];"
          f"[b]scale={W}:{H}:force_original_aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2[v0]")
    inputs = ["-i", str(src)]
    if cap:
        inputs += ["-i", str(cap)]
        vf += ";[v0][1:v]overlay=0:0[v]"
    else:
        vf += ";[v0]null[v]"
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", vf, "-map", "[v]", "-t", str(dur), "-an",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", str(out)])


def still(png, out, dur):
    run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-i", str(png), "-vf",
         f"scale=2112:-2,zoompan=z='min(zoom+0.0006,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={int(dur * 30)}:s={W}x{H}:fps=30",
         "-t", str(dur), "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "19", "-pix_fmt", "yuv420p", str(out)])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--title", required=True)
    ap.add_argument("--jog", required=True)
    ap.add_argument("--redo")
    ap.add_argument("--sim", required=True)
    ap.add_argument("--sim2")
    ap.add_argument("--sim2_start", type=float, default=2.0)
    ap.add_argument("--music", default="web/audio/loop.mp3")
    ap.add_argument("--out", default="media/out/cityquest_submission.mp4")
    a = ap.parse_args()
    tmp = pathlib.Path(tempfile.mkdtemp(prefix="cq-sub-"))
    caps = {
        "c1": ("20 minutes. A coffee and a croissant.", "What is actually open right now?"),
        "c2": ("Gemini Live sees the street.", "The block becomes a live simulation."),
        "c3": ("Every place checked live. Argon plans.", "A sandboxed managed agent proves the route."),
        "c4": ("Any street, any judge, live.", "2,088 places and their reviews in one gemini-4-argon context."),
    }
    for k, (t, s) in caps.items():
        caption_png(t, tmp / f"{k}.png", s)
    parts = []
    still(a.title, tmp / "p0.mp4", 3.0); parts.append(tmp / "p0.mp4")
    fit(a.jog, tmp / "p1.mp4", 0, 11, cap=tmp / "c1.png"); parts.append(tmp / "p1.mp4")
    if a.redo:
        fit(a.redo, tmp / "p2.mp4", 0, 8, cap=tmp / "c2.png"); parts.append(tmp / "p2.mp4")
    fit(a.sim, tmp / "p3.mp4", 2, 26, cap=tmp / "c3.png"); parts.append(tmp / "p3.mp4")
    if a.sim2:
        fit(a.sim2, tmp / "p4.mp4", a.sim2_start, 16, cap=tmp / "c4.png"); parts.append(tmp / "p4.mp4")
    still(a.title, tmp / "p5.mp4", 3.0); parts.append(tmp / "p5.mp4")
    lst = tmp / "list.txt"
    lst.write_text("".join(f"file '{p}'\n" for p in parts))
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(tmp / "video.mp4")])
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(tmp / "video.mp4")],
                               capture_output=True, text=True).stdout.strip())
    out = pathlib.Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(tmp / "video.mp4"), "-stream_loop", "-1", "-i", a.music,
         "-filter_complex", f"[1:a]atrim=0:{dur},afade=t=in:d=1.5,afade=t=out:st={dur - 2.5}:d=2.5,volume=0.8[m]",
         "-map", "0:v", "-map", "[m]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest", str(out)])
    print(f"wrote {out} ({dur:.1f} s)")


if __name__ == "__main__":
    main()
