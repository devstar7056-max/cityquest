#!/usr/bin/env python3
"""Build and prime City Memory: python3 scripts/build_city_memory.py "San Francisco Ferry Building" [half_km]

Needs MAPS_SERVER_KEY and GEMINI_API_KEY. Writes data/city_memory.jsonl and data/city_memory.json.
"""
import asyncio
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))
from server import citymem  # noqa: E402


async def main():
    center = sys.argv[1] if len(sys.argv) > 1 else "San Francisco Ferry Building"
    half_km = float(sys.argv[2]) if len(sys.argv) > 2 else 2.5
    rows, stats = await citymem.build(center, half_km=half_km)
    approx = sum(len(str(r)) for r in rows) // 4
    print(f"snapshot about {approx:,} tokens (chars/4) before priming")
    if approx > 880_000:
        rows.sort(key=lambda r: -(r.get("n") or 0))
        while sum(len(str(r)) for r in rows) // 4 > 850_000:
            rows.pop()
        stats["places"] = len(rows)
        print(f"trimmed to {len(rows)} most-reviewed places to stay inside the 1M window with room to plan")
    meta = await citymem.prime(rows, stats)
    print(meta["ack"])


asyncio.run(main())
