#!/usr/bin/env python3
"""Snapshot the Google I/O Hackathon gallery (Cerebral Valley) into data/io_gallery.json.

Reads the page's schema.org ItemList (name, url, description, award, creators, links).
The Live guide answers "who won" from this file and cites the gallery URL. Standard library only.
"""
import json
import pathlib
import re
import time
import urllib.request

URL = "https://cerebralvalley.ai/e/google-io-hackathon/hackathon/gallery"
OUT = pathlib.Path(__file__).resolve().parent.parent / "data" / "io_gallery.json"


def objects(s, start_pat):
    """Yield balanced-brace JSON objects that start with start_pat."""
    for m in re.finditer(re.escape(start_pat), s):
        depth, i, in_str, esc = 0, m.start(), False, False
        for j in range(i, len(s)):
            c = s[j]
            if in_str:
                esc = (c == "\\" and not esc)
                if c == '"' and not esc:
                    in_str = False
                continue
            if c == '"':
                in_str = True
            elif c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    yield s[i:j + 1]
                    break


def snapshot():
    """Fetch the gallery now and return the parsed snapshot."""
    html = urllib.request.urlopen(urllib.request.Request(URL, headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read().decode()
    parts = re.findall(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', html, re.S)
    for c in re.findall(r'self\.__next_f\.push\(\[1,"(.*?)"\]\)', html, re.S):
        try:
            parts.append(json.loads('"' + c + '"'))  # each chunk is a JSON string literal
        except json.JSONDecodeError:
            parts.append(c.replace('\\"', '"'))
    s = "\n".join(parts)
    seen, projects = set(), []
    for raw in objects(s, '{"@type":"ListItem"'):
        try:
            item = json.loads(raw).get("item", {})
        except json.JSONDecodeError:
            continue
        if not isinstance(item, dict) or item.get("url") in seen or not item.get("name"):  # breadcrumbs use a string
            continue
        seen.add(item["url"])
        creators = item.get("creator") or []
        creators = creators if isinstance(creators, list) else [creators]
        projects.append({"name": item["name"], "url": item["url"], "award": item.get("award"),
                         "description": item.get("description"), "team": [c.get("name") for c in creators],
                         "links": item.get("sameAs") or []})
    order = {"1st Place": 0, "2nd Place": 1, "3rd Place": 2, "Finalist": 3}
    winners = sorted([p for p in projects if p["award"]], key=lambda p: order.get(p["award"], 9))
    return {"source": URL, "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "project_count": len(projects), "winners": winners, "projects": projects}


def main():
    snap = snapshot()
    OUT.write_text(json.dumps(snap, indent=1))
    print(f"{snap['project_count']} projects, {len(snap['winners'])} with awards -> {OUT.name}")
    for w in snap["winners"]:
        print(f"  {w['award']:<10} {w['name']}: {', '.join(w['team'])}")


if __name__ == "__main__":
    main()
