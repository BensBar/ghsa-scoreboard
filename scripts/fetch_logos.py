#!/usr/bin/env python3
"""Download MaxPreps school mascots; generate monogram PNG fallbacks."""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
SCHOOLS_PATH = ROOT / "data" / "schools.json"
LOGO_DIR = ROOT / "assets" / "logos"
UA = "Mozilla/5.0 (compatible; GHSA-Scoreboard/1.1; +https://github.com/BensBar/ghsa-scoreboard)"

# Extra MaxPreps team pages for catalog schools missing links
MAXPREPS_TEAM = {
    "buford": "https://www.maxpreps.com/ga/buford/buford-wolves/football/",
    "gainesville": "https://www.maxpreps.com/ga/gainesville/gainesville-red-elephants/football/",
    "mill-creek": "https://www.maxpreps.com/ga/hoschton/mill-creek-hawks/football/",
    "north-gwinnett": "https://www.maxpreps.com/ga/suwanee/north-gwinnett-bulldogs/football/",
    "collins-hill": "https://www.maxpreps.com/ga/suwanee/collins-hill-eagles/football/",
    "grayson": "https://www.maxpreps.com/ga/loganville/grayson-rams/football/",
    "colquitt-county": "https://www.maxpreps.com/ga/moultrie/colquitt-county-packers/football/",
    "valdosta": "https://www.maxpreps.com/ga/valdosta/valdosta-wildcats/football/",
    "lowndes": "https://www.maxpreps.com/ga/valdosta/lowndes-vikings/football/",
    "lee-county": "https://www.maxpreps.com/ga/leesburg/lee-county-trojans/football/",
    "milton": "https://www.maxpreps.com/ga/milton/milton-eagles/football/",
    "roswell": "https://www.maxpreps.com/ga/roswell/roswell-hornets/football/",
    "norcross": "https://www.maxpreps.com/ga/norcross/norcross-blue-devils/football/",
    "peachtree-ridge": "https://www.maxpreps.com/ga/suwanee/peachtree-ridge-lions/football/",
    "creekside": "https://www.maxpreps.com/ga/fairburn/creekside-seminoles/football/",
    "jefferson": "https://www.maxpreps.com/ga/jefferson/jefferson-dragons/football/",
}

# Opponent / top-game side teams we also want logos for
OPPONENTS = {
    "forsyth-central": {
        "name": "Forsyth Central",
        "primaryColor": "#003366",
        "maxpreps": "https://www.maxpreps.com/ga/cumming/forsyth-central-bulldogs/football/",
    },
    "mountain-view": {
        "name": "Mountain View",
        "primaryColor": "#1a3a6b",
        "maxpreps": "https://www.maxpreps.com/ga/lawrenceville/mountain-view-bears/football/",
    },
    "catholic-br": {
        "name": "Catholic BR",
        "primaryColor": "#6b1f2a",
        "maxpreps": "https://www.maxpreps.com/la/baton-rouge/catholic-bears/football/",
    },
    "east-paulding": {
        "name": "East Paulding",
        "primaryColor": "#0a3d2e",
        "maxpreps": "https://www.maxpreps.com/ga/dallas/east-paulding-raiders/football/",
    },
    "mallard-creek": {
        "name": "Mallard Creek",
        "primaryColor": "#003087",
        "maxpreps": "https://www.maxpreps.com/nc/charlotte/mallard-creek-mavericks/football/",
    },
    "east-st-louis": {
        "name": "East St. Louis",
        "primaryColor": "#ff6600",
        "maxpreps": "https://www.maxpreps.com/il/east-st-louis/east-st-louis-flyers/football/",
    },
    "st-joseph-regional": {
        "name": "St. Joe's NJ",
        "primaryColor": "#003366",
        "maxpreps": "https://www.maxpreps.com/nj/montvale/st-joseph-regional-green-knights/football/",
    },
    "peach-county": {
        "name": "Peach County",
        "primaryColor": "#8b0000",
        "maxpreps": "https://www.maxpreps.com/ga/fort-valley/peach-county-trojans/football/",
    },
    "northside-wr": {
        "name": "Northside WR",
        "primaryColor": "#003399",
        "maxpreps": "https://www.maxpreps.com/ga/warner-robins/northside-eagles/football/",
    },
    "warner-robins": {
        "name": "Warner Robins",
        "primaryColor": "#c41e3a",
        "maxpreps": "https://www.maxpreps.com/ga/warner-robins/warner-robins-demons/football/",
    },
}

COLORS = {
    "chattahoochee": "#1e4d8c",
    "johns-creek": "#1a2a4a",
    "carrollton": "#8b1a2b",
    "central-of-carrollton": "#003087",
    "buford": "#1b5e20",
    "gainesville": "#b71c1c",
    "mill-creek": "#0d47a1",
    "north-gwinnett": "#00205b",
    "collins-hill": "#2e7d32",
    "grayson": "#1a237e",
    "colquitt-county": "#212121",
    "valdosta": "#c62828",
    "lowndes": "#4a148c",
    "lee-county": "#e65100",
    "milton": "#1b5e20",
    "roswell": "#1565c0",
    "norcross": "#0d47a1",
    "peachtree-ridge": "#263238",
    "creekside": "#212121",
    "jefferson": "#b71c1c",
}


def fetch(url: str, timeout: int = 25) -> bytes | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read()
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        print(f"  fetch fail: {url[:80]} -> {exc}", file=sys.stderr)
        return None


def extract_mascot_url(html: str) -> str | None:
    # Prefer largest school-mascot URL for the primary school (first large one)
    matches = re.findall(
        r'https://image\.maxpreps\.io/school-mascot/[0-9a-f/]+[0-9a-f-]{36}\.gif\?[^"\'\\\s<>]+',
        html,
        flags=re.I,
    )
    if not matches:
        # unescape amp
        matches = re.findall(
            r'https://image\.maxpreps\.io/school-mascot/[0-9a-f/]+[0-9a-f-]{36}\.gif[^"\'\\\s<>]*',
            html,
            flags=re.I,
        )
    cleaned = []
    for m in matches:
        u = m.replace("&amp;", "&").replace("\\u0026", "&")
        # bump to 256 if width present
        u = re.sub(r"width=\d+", "width=256", u)
        u = re.sub(r"height=\d+", "height=256", u)
        if "width=" not in u:
            u += ("&" if "?" in u else "?") + "width=256&height=256"
        cleaned.append(u)
    # most common id on page is usually the home school
    if not cleaned:
        return None
    from collections import Counter
    ids = [re.search(r"school-mascot/([0-9a-f/]+[0-9a-f-]{36})", u).group(1) for u in cleaned]
    top = Counter(ids).most_common(1)[0][0]
    for u in cleaned:
        if top in u and "width=256" in u:
            return u
    return cleaned[0]


def initials(name: str) -> str:
    parts = re.findall(r"[A-Za-z0-9]+", name)
    if not parts:
        return "?"
    if len(parts) == 1:
        return parts[0][:2].upper()
    # Central of Carrollton -> CC, Colquitt County -> CC, North Gwinnett -> NG
    skip = {"of", "the", "and", "de", "la"}
    keep = [p for p in parts if p.lower() not in skip]
    if len(keep) >= 2:
        return (keep[0][0] + keep[1][0]).upper()
    return keep[0][:2].upper()


def hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore


def make_monogram(path: Path, name: str, color: str, size: int = 256) -> None:
    rgb = hex_to_rgb(color)
    # darken for bg
    bg = tuple(max(0, int(c * 0.35)) for c in rgb)
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(im)
    pad = 6
    draw.ellipse([pad, pad, size - pad, size - pad], fill=bg + (255,), outline=rgb + (255,), width=8)
    # inner ring
    draw.ellipse([pad + 18, pad + 18, size - pad - 18, size - pad - 18], outline=(255, 255, 255, 60), width=2)
    text = initials(name)
    # font
    font = None
    for fp in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSansBold.ttf",
    ):
        if Path(fp).exists():
            font = ImageFont.truetype(fp, 96 if len(text) <= 2 else 72)
            break
    if font is None:
        font = ImageFont.load_default()
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    xy = ((size - tw) / 2 - bbox[0], (size - th) / 2 - bbox[1] - 4)
    draw.text(xy, text, fill=(255, 255, 255, 255), font=font)
    im.save(path, "PNG")


def save_mascot_png(data: bytes, path: Path) -> bool:
    try:
        im = Image.open(BytesIO(data))
        im = im.convert("RGBA")
        # trim near-transparent edges lightly by ensuring square canvas
        im.thumbnail((256, 256), Image.Resampling.LANCZOS)
        canvas = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
        x = (256 - im.width) // 2
        y = (256 - im.height) // 2
        canvas.paste(im, (x, y), im)
        canvas.save(path, "PNG", optimize=True)
        return True
    except Exception as exc:
        print(f"  decode fail: {exc}", file=sys.stderr)
        return False


def process(sid: str, name: str, color: str, team_url: str | None) -> str:
    LOGO_DIR.mkdir(parents=True, exist_ok=True)
    out = LOGO_DIR / f"{sid}.png"
    source = "monogram"
    if team_url:
        print(f"[{sid}] fetching {team_url}")
        html_b = fetch(team_url)
        if html_b:
            html = html_b.decode("utf-8", errors="replace")
            mascot = extract_mascot_url(html)
            if mascot:
                print(f"  mascot: {mascot[:90]}...")
                img = fetch(mascot)
                if img and save_mascot_png(img, out):
                    source = "maxpreps"
                    print(f"  saved maxpreps -> {out.name}")
                    return source
    print(f"[{sid}] monogram fallback")
    make_monogram(out, name, color)
    return source


def main() -> int:
    data = json.loads(SCHOOLS_PATH.read_text())
    results = {}

    for school in data["schools"]:
        sid = school["id"]
        color = COLORS.get(sid, school.get("primaryColor", "#3dff9a"))
        school["primaryColor"] = color
        team = None
        if school.get("maxpreps", {}).get("team"):
            team = school["maxpreps"]["team"]
        elif sid in MAXPREPS_TEAM:
            team = MAXPREPS_TEAM[sid]
            school.setdefault("maxpreps", {})["team"] = team
        src = process(sid, school["name"], color, team)
        school["logo"] = f"assets/logos/{sid}.png"
        results[sid] = src

    # opponents meta file for client
    opp_meta = {}
    for oid, meta in OPPONENTS.items():
        src = process(oid, meta["name"], meta["primaryColor"], meta.get("maxpreps"))
        opp_meta[oid] = {
            "id": oid,
            "name": meta["name"],
            "primaryColor": meta["primaryColor"],
            "logo": f"assets/logos/{oid}.png",
            "source": src,
        }
        results[oid] = src

    data["opponents"] = list(opp_meta.values())
    SCHOOLS_PATH.write_text(json.dumps(data, indent=2) + "\n")
    print("\nSummary:")
    for k, v in results.items():
        print(f"  {k}: {v}")
    print("wrote", SCHOOLS_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
