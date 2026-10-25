#!/usr/bin/env python3
"""CityQuest submission video v2: story-first cut, about 74 s, 1920x1080, 30 fps.

Story: Rakesh at the Ferry Building with 20 minutes -> what is open? -> CityQuest sees the
street -> live scan -> Argon plans -> the verifier proves it (today's logged 2:37 PM run)
-> replan -> any street + City Memory -> human control + open source -> end card.
Every number on screen comes from AGENTS.md / README.md measurements.

Run from the repo root:  python3 scripts/make_submission_v2.py
Segments are cached in ~/cq_v2; delete that folder to rebuild from scratch.
"""
import pathlib
import subprocess
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = pathlib.Path(__file__).resolve().parent.parent
M = ROOT / "media"
OUT = M / "out" / "cityquest_submission_v2.mp4"
WORK = pathlib.Path.home() / "cq_v2"
WORK.mkdir(exist_ok=True)
W, H, FPS = 1920, 1080, 30
ENC = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p", "-r", str(FPS)]

GF = "/usr/share/fonts/truetype/google-fonts/"
BOLD, MED, REG = GF + "Poppins-Bold.ttf", GF + "Poppins-Medium.ttf", GF + "Poppins-Regular.ttf"
MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Bold.ttf"
CREAM, BLUE, GREEN = (244, 237, 225, 255), (110, 178, 255, 255), (72, 214, 120, 255)
RED, AMBER, GRAY = (255, 96, 84, 255), (255, 188, 70, 255), (156, 168, 186, 255)


def F(path, size):
    return ImageFont.truetype(path, size)


def run(args):
    r = subprocess.run(args, capture_output=True, text=True)
    if r.returncode:
        print(r.stderr[-1500:])
        sys.exit(f"ffmpeg failed: {' '.join(map(str, args))[:200]}")


def wrap(d, text, font, maxw):
    lines, cur = [], ""
    for w in text.split():
        t = (cur + " " + w).strip()
        if d.textlength(t, font=font) <= maxw:
            cur = t
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def side_panel(path, blocks, x=840, maxw=980):
    """blocks: (text, font_path, size, color, gap_after). Vertically centred column on the right."""
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    rows, total = [], 0
    for text, fp, size, color, gap in blocks:
        f = F(fp, size)
        lines = wrap(d, text, f, maxw)
        lh = int(size * 1.28)
        rows.append((lines, f, color, lh, gap))
        total += lh * len(lines) + gap
    y = (H - total) // 2
    for lines, f, color, lh, gap in rows:
        for ln in lines:
            d.text((x, y), ln, font=f, fill=color)
            y += lh
        y += gap
    img.save(path)


def lower_third(path, title, sub=None, tag=None):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    ft, fs, fg = F(BOLD, 50), F(MED, 31), F(REG, 23)
    tl = wrap(d, title, ft, 1380)
    sl = wrap(d, sub, fs, 1380) if sub else []
    bw = max([d.textlength(l, font=ft) for l in tl] + [d.textlength(l, font=fs) for l in sl]) + 84
    bh = 34 + 66 * len(tl) + (8 + 44 * len(sl) if sl else 0) + 26
    x0, y0 = 72, H - 70 - bh
    d.rounded_rectangle([x0, y0, x0 + bw, y0 + bh], radius=24, fill=(7, 13, 25, 218))
    d.rounded_rectangle([x0 + 20, y0 + 26, x0 + 27, y0 + bh - 26], radius=3, fill=BLUE)
    y = y0 + 26
    for l in tl:
        d.text((x0 + 50, y), l, font=ft, fill=CREAM)
        y += 66
    y += 8
    for l in sl:
        d.text((x0 + 50, y), l, font=fs, fill=BLUE)
        y += 44
    if tag:
        tw = d.textlength(tag, font=fg)
        d.rounded_rectangle([W - 60 - tw - 36, 40, W - 60, 86], radius=20, fill=(7, 13, 25, 200))
        d.text((W - 60 - tw - 18, 49), tag, font=fg, fill=GRAY)
    img.save(path)


def log_panel(path, header, lines, upto, footer):
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    fh, fm, ff = F(BOLD, 31), F(MONO, 26), F(REG, 22)
    x0, y0, x1 = 990, 110, 1870
    bh = 92 + 50 * len(lines) + 64
    d.rounded_rectangle([x0, y0, x1, y0 + bh], radius=22, fill=(5, 9, 17, 232), outline=(64, 86, 120, 255), width=2)
    d.text((x0 + 34, y0 + 26), header, font=fh, fill=CREAM)
    y = y0 + 92
    for txt, color in lines[:upto]:
        d.text((x0 + 34, y), txt, font=fm, fill=color)
        y += 50
    d.text((x0 + 34, y0 + bh - 46), footer, font=ff, fill=GRAY)
    img.save(path)


def phone_seg(name, src, ss, dur, panel):
    out = WORK / f"{name}.mp4"
    if out.exists():
        return out
    vf = (f"[1:v]setpts=PTS-STARTPTS,fps={FPS},scale=-2:920,pad=iw+8:ih+8:4:4:color=0xDCE6F3[ph];"
          f"[0:v][ph]overlay=200:76:shortest=1[a];[a][2:v]overlay=0:0,"
          f"fade=t=in:st=0:d=0.3,fade=t=out:st={dur - 0.3}:d=0.3,format=yuv420p[v]")
    run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", f"color=c=0x0B1628:s={W}x{H}:r={FPS}:d={dur}",
         "-ss", str(ss), "-t", str(dur), "-i", str(src), "-loop", "1", "-t", str(dur), "-i", str(panel),
         "-filter_complex", vf, "-map", "[v]", "-t", str(dur), "-an", *ENC, str(out)])
    return out


def full_seg(name, src, ss, dur, overlays):
    """overlays: (png, start, end) shown with enable windows."""
    out = WORK / f"{name}.mp4"
    if out.exists():
        return out
    inputs = ["-ss", str(ss), "-t", str(dur), "-i", str(src)]
    for png, _, _ in overlays:
        inputs += ["-loop", "1", "-t", str(dur), "-i", str(png)]
    fc = f"[0:v]setpts=PTS-STARTPTS,fps={FPS},scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H}[b0]"
    last = "b0"
    for i, (_, a, b) in enumerate(overlays, start=1):
        fc += f";[{last}][{i}:v]overlay=0:0:enable='between(t,{a},{b})'[b{i}]"
        last = f"b{i}"
    fc += f";[{last}]fade=t=in:st=0:d=0.3,fade=t=out:st={dur - 0.3}:d=0.3,format=yuv420p[v]"
    run(["ffmpeg", "-y", "-v", "error", *inputs, "-filter_complex", fc, "-map", "[v]", "-t", str(dur),
         "-an", *ENC, str(out)])
    return out


def end_card(name, dur, text_png):
    out = WORK / f"{name}.mp4"
    if out.exists():
        return out
    bg = WORK / "title_1080.png"
    Image.open(M / "work" / "title_card.png").convert("RGB").resize((1920, 1086)).crop((0, 3, 1920, 1083)).save(bg)
    vf = (f"[0:v]scale=2112:-2,zoompan=z='min(zoom+0.0005,1.05)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
          f":d={int(dur * FPS)}:s={W}x{H}:fps={FPS}[bg];[bg][1:v]overlay=0:0,fade=t=in:st=0:d=0.4,format=yuv420p[v]")
    run(["ffmpeg", "-y", "-v", "error", "-loop", "1", "-t", str(dur), "-i", str(bg), "-loop", "1", "-t", str(dur),
         "-i", str(text_png), "-filter_complex", vf, "-map", "[v]", "-t", str(dur), "-an", *ENC, str(out)])
    return out


def main():
    raw41, raw58 = M / "raw" / "jog_15-31-41.mp4", M / "raw" / "jog_15-31-58.mp4"
    seed = M / "work" / "jog_redo_seedance.mp4"
    tiles = ROOT / "web" / "fixtures" / "TEST_ferry_3dtiles_tts_voice.mp4"
    simA, simB, simC = (M / "work" / f"sim_rec_{t}.webm" for t in ("160247", "160501", "160637"))
    P = lambda n: WORK / f"{n}.png"

    side_panel(P("p1"), [
        ("3:31 PM  ·  SUNDAY  ·  THE FERRY BUILDING", BOLD, 28, BLUE, 26),
        ("i have 20 minutes.", BOLD, 70, CREAM, 0),
        ("A coffee and a croissant.", BOLD, 70, CREAM, 22),
        ("What's actually open right now?", BOLD, 44, AMBER, 34),
        ("Rakesh, at the Gemini 4 Argon SF Hackathon. Real footage.", REG, 26, GRAY, 0)])
    side_panel(P("p2"), [
        ("Maps show pins.", BOLD, 66, CREAM, 18),
        ("They don't know your time, what's open right now, or that you'll change your mind.", MED, 42, CREAM, 0)])
    side_panel(P("p3"), [
        ("CITYQUEST", BOLD, 28, BLUE, 18),
        ("Your next 20 minutes, as a quest.", BOLD, 62, CREAM, 18),
        ("Every stop is real. Every stop is checked.", MED, 40, BLUE, 34),
        ("Stylized transition: Higgsfield Seedance, made from the real footage.", REG, 24, GRAY, 0)])
    lower_third(P("l4"), "Gemini 3.8 Live sees where you are and hears the ask.",
                "Camera at 1 fps plus the mic  ·  interrupt any time  ·  ephemeral tokens",
                tag="Google Photorealistic 3D Tiles")
    lower_third(P("l5a"), "45 places in the Ferry Building, checked live",
                "Places API in parallel, under 0.5 s  ·  open now, coffee, breakfast, dessert, price range")
    lower_third(P("l5b"), "37 open on a Sunday afternoon", "Green pins are open right now. Red are closed.")
    lower_third(P("l5c"), "gemini-4-argon plans the quest",
                "Structured JSON, only real place IDs from the official Ferry Building map")
    lines = [("director  gemini-4-argon  4 stops   10.8 s", CREAM),
             ("routes    WALK   46 of 45 min      FAIL", RED),
             ("verifier  drop Pier 14, rerun", AMBER),
             ("routes    WALK   27 of 45 min      PASS", GREEN),
             ("agent     antigravity-preview-09-2026", BLUE),
             ("          same verdict, in a Google sandbox", BLUE)]
    for n in range(1, len(lines) + 1):
        log_panel(P(f"log{n}"), "PROVING THE PLAN  ·  REAL RUN, 2:37 PM", lines, n,
                  "From today's logged run. Nothing in the HUD is mocked.")
    lower_third(P("l6"), "Every plan is proven before you take a step.",
                "Live Places hours + Routes walking time, checked in code, fixed, re-checked")
    lower_third(P("l7"), "Change your mind mid-sentence.",
                "“Only 15 minutes, something sweet.”  Replanned and re-verified in 11.0 s.")
    lower_third(P("l8a"), "Name any street.", "It flies there, scans, plans and verifies live. Nothing precomputed.")
    lower_third(P("l8b"), "City Memory: 2,088 places in one gemini-4-argon context",
                "With their Google reviews  ·  565,115 input tokens, API-reported")
    side_panel(P("p9"), [
        ("It never books, buys or messages anyone.", BOLD, 54, CREAM, 10),
        ("It only plans and checks. You stay in control.", MED, 36, BLUE, 44),
        ("Next: open source.", BOLD, 50, CREAM, 10),
        ("A verified next-hour engine for conferences, campuses, airports and city guides.", MED, 36, CREAM, 0)])
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.text((132, 690), "Change your plans, and the world changes with you.", font=F(BOLD, 44), fill=CREAM)
    stack = ("gemini-4-argon  ·  Antigravity managed agent  ·  Gemini 3.8 Live  ·  3.8 Flash  ·  "
             "3.5 Flash-Lite  ·  Nano Banana 2.1  ·  Lyria  ·  Deep Research  ·  "
             "Maps 3D Tiles, Places, Routes  ·  Cloud Run")
    y = 778
    for ln in wrap(d, stack, F(REG, 24), 1040):
        d.text((132, y), ln, font=F(REG, 24), fill=GRAY)
        y += 36
    d.text((132, y + 26), "Built today by Rakesh at the Gemini 4 Argon SF Hackathon, Oct 25, 2026",
           font=F(MED, 26), fill=BLUE)
    img.save(P("end"))

    segs = [
        phone_seg("s01", raw58, 33.0, 5.0, P("p1")),
        phone_seg("s02", raw41, 15.0, 5.0, P("p2")),
        phone_seg("s03", seed, 0.0, 5.5, P("p3")),
        full_seg("s04", tiles, 0.5, 3.5, [(P("l4"), 0, 3.5)]),
        full_seg("s05", simA, 0.5, 17.0, [(P("l5a"), 0, 6), (P("l5b"), 6, 11.5), (P("l5c"), 11.5, 17)]),
        full_seg("s06", simB, 20.0, 10.0, [(P("l6"), 0, 10)] +
                 [(P(f"log{n}"), 0.4 + 1.1 * (n - 1), 10 if n == len(lines) else 0.4 + 1.1 * n)
                  for n in range(1, len(lines) + 1)]),
        full_seg("s07", simC, 12.0, 7.0, [(P("l7"), 0, 7)]),
        full_seg("s08", simC, 39.0, 9.5, [(P("l8a"), 0, 4.5), (P("l8b"), 4.5, 9.5)]),
        phone_seg("s09", raw41, 64.0, 6.0, P("p9")),
        end_card("s10", 5.5, P("end")),
    ]
    lst = WORK / "list.txt"
    lst.write_text("".join(f"file '{s}'\n" for s in segs))
    video = WORK / "video.mp4"
    run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(video)])
    dur = float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                str(video)], capture_output=True, text=True).stdout.strip())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-stream_loop", "-1", "-i", str(ROOT / "web" / "audio" / "loop.mp3"),
         "-filter_complex", f"[1:a]atrim=0:{dur},afade=t=in:d=1.2,afade=t=out:st={dur - 2.5}:d=2.5,volume=0.85[m]",
         "-map", "0:v", "-map", "[m]", "-c:v", "copy", "-c:a", "aac", "-b:a", "160k", "-shortest",
         "-movflags", "+faststart", str(OUT)])
    print(f"wrote {OUT} ({dur:.1f} s)")


if __name__ == "__main__":
    main()
