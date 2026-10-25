"""SSE step stream for the HUD. One broadcast bus; every event carries its run_id."""
import asyncio
import json
import time
from datetime import datetime

_subscribers: set[asyncio.Queue] = set()


def emit(run_id, step, status, ms=None, detail=None, **extra):
    ev = {"t": datetime.now().astimezone().isoformat(timespec="milliseconds"), "run_id": run_id,
          "step": step, "status": status, "ms": ms, "detail": detail, **extra}
    for q in list(_subscribers):
        try:
            q.put_nowait(ev)
        except asyncio.QueueFull:
            pass
    return ev


async def stream():
    q: asyncio.Queue = asyncio.Queue(maxsize=500)
    _subscribers.add(q)
    try:
        yield "retry: 1500\n\n"
        while True:
            try:
                ev = await asyncio.wait_for(q.get(), timeout=15)
                yield f"data: {json.dumps(ev, ensure_ascii=False)}\n\n"
            except asyncio.TimeoutError:
                yield f": ping {time.time():.0f}\n\n"
    finally:
        _subscribers.discard(q)
