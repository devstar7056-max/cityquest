#!/usr/bin/env python3
"""CityQuest submission video v3: AI hero shots (Higgsfield Seedance 2.5) + real product footage
+ narration (Higgsfield text2speech, ElevenLabs engine) + Lyria loop. About 70 s, 1920x1080.

Reuses the product segments rendered by make_submission_v2.py (in ~/cq_v2).
Usage: python3 scripts/make_submission_v3.py --clip1 A.mp4 --clip2 B.mp4 --vo narration.mp3
"""
import argparse, pathlib, re, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import make_submission_v2 as v2  # noqa: E402

W, H, FPS, WORK = v2.W, v2.H, v2.FPS, v2.WORK
ROOT = v2.ROOT
OUT = ROOT / "media" / "out" / "cityquest_submission_v3.mp4"
TAG = "AI-generated scene  ·  Higgsfield Seedance 2.5"
# narration line slots (start, end) in seconds on the final timeline
SLOTS = [(0.4, 6.0), (6.2, 12.0), (12.2, 15.5), (15.8, 32.5), (32.8, 42.5), (42.8, 49.5),
         (49.8, 59.0), (59.3, 65.0), (65.4, 70.3)]


def probe_dur(p):
    return float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0",
                                 str(p)], capture_output=True, text=True).stdout.strip())


def silences(vo):
    r = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(vo), "-af", "silencedetect=noise=-35dB:d=0.30",
                        "-f", "null", "-"], capture_output=True, text=True)
    starts = [float(x) for x in re.findall(r"silence_start: ([0-9.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([0-9.]+)", r.stderr)]
    return list(zip(starts, ends))


def split_points(vo, n_lines):
    total = probe_dur(vo)
    gaps = [(e - s, s, e) for s, e in silences(vo) if s > 0.2 and e < total - 0.2]
    gaps.sort(reverse=True)
    pick = sorted(gaps[:n_lines - 1], key=lambda g: g[1])
    if len(pick) < n_lines - 1:
        return None, total
    cuts = [0.0] + [(s + e) / 2 for _, s, e in pick] + [total]
    return cuts, total


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--clip1", required=True)
    ap.add_argument("--clip2", required=True)
    ap.add_argument("--vo", required=True)
    a = ap.parse_args()
    P = lambda n: WORK / f"{n}.png"
    v2.lower_third(P("ai1a"), "20 minutes. A coffee and a croissant.", "In a city you don't know, what's actually open right now?", tag=TAG)
    v2.lower_third(P("ai1b"), "CityQuest turns the street you're on into a quest.", "Every stop is real. Every stop is checked.", tag=TAG)
    v2.lower_third(P("ai2"), "It never books, buys or messages anyone.",
                   "It only plans and checks. Next: open source for conferences, campuses and airports.", tag=TAG)
    for n in ("a1", "a2"):
        (WORK / f"{n}.mp4").unlink(missing_ok=True)
    a1 = v2.full_seg("a1", a.clip1, 0.0, 12.0, [(P("ai1a"), 0, 6.0), (P("ai1b"), 6.0, 12.0)])
    a2 = v2.full_seg("a2", a.clip2, 0.0, 6.0, [(P("ai2"), 0, 6.0)])
    segs = [a1] + [WORK / f"s0{i}.mp4" for i in (4, 5, 6, 7, 8)] + [a2, WORK / "s10.mp4"]
    for s in segs:
        if not pathlib.Path(s).exists():
            sys.exit(f"missing segment {s}; run make_submission_v2.py first")
    lst = WORK / "list3.txt"
    lst.write_text("".join(f"file '{s}'\n" for s in segs))
    video = WORK / "video3.mp4"
    v2.run(["ffmpeg", "-y", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(video)])
    dur = probe_dur(video)

    cuts, vo_total = split_points(a.vo, len(SLOTS))
    music = ROOT / "web" / "audio" / "loop.mp3"
    fc, labels = [], []
    if cuts:
        fc.append(f"[1:a]aformat=sample_rates=48000:channel_layouts=stereo,asplit={len(SLOTS)}" +
                  "".join(f"[v{i}]" for i in range(len(SLOTS))))
        prev_end = 0.0
        for i, (s0, e0) in enumerate(SLOTS):
            ln = cuts[i + 1] - cuts[i]
            room = (e0 - s0) - 0.15
            tempo = min(1.15, ln / room) if ln > room else 1.0
            start = max(s0, prev_end + 0.1)
            prev_end = start + ln / tempo
            fc.append(f"[v{i}]atrim={cuts[i]:.3f}:{cuts[i + 1]:.3f},asetpts=PTS-STARTPTS,"
                      f"atempo={tempo:.3f},adelay={int(start * 1000)}|{int(start * 1000)}[l{i}]")
            labels.append(f"[l{i}]")
            print(f"line {i + 1}: {ln:.2f} s at {start:.2f} s (tempo {tempo:.2f})")
        fc.append("".join(labels) + f"amix=inputs={len(labels)}:normalize=0[vo]")
    else:
        print("could not split narration; placing it whole at 0.4 s")
        fc.append("[1:a]aformat=sample_rates=48000:channel_layouts=stereo,adelay=400|400[vo]")
    fc.append(f"[2:a]aformat=sample_rates=48000:channel_layouts=stereo,atrim=0:{dur},"
              f"afade=t=in:d=1.0,afade=t=out:st={dur - 2.5}:d=2.5,volume=0.28[m]")
    fc.append("[vo]volume=1.0[vv];[vv][m]amix=inputs=2:normalize=0:duration=longest,"
              f"atrim=0:{dur},alimiter=limit=0.95[aout]")
    v2.run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(a.vo), "-stream_loop", "-1", "-i", str(music),
            "-filter_complex", ";".join(fc), "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac",
            "-b:a", "192k", "-shortest", "-movflags", "+faststart", str(OUT)])
    print(f"wrote {OUT} ({dur:.1f} s, narration {vo_total:.1f} s)")


if __name__ == "__main__":
    main()
