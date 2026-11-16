#!/usr/bin/env python3
"""
Mirror the covers assigned by the classifier into the local cover store.

RomM only sees the rclone mount, and that mount contains the ROM files but not
the covers. The community app does store the cover of every game (RAWG today,
ScreenScraper or another provider later) as a URL in `nzbs.poster_url`. This
script asks the community for that list and downloads/changes nothing else:

  GET /api/rclone/game-covers  ->  { games: [{ filename, posterUrl, ... }] }

Each image is converted to a 512 px WebP named after its own sha256, so the
same file names used by the bulk import keep working:

  <work>/covers/<hash>.webp
  <work>/remote-games.json   (filename -> platform/title/year/cover/sourceUrl)

`build_library.py` reads `remote-games.json` and uses those covers for games
that were not part of the normalized import.

It runs inside the RomM image, which already ships Python + Pillow.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from PIL import Image

# contentType -> normalized folder name used by build_library.py
CONTENT_TYPE_PLATFORMS: dict[str, str] = {
    "game_gb": "Game Boy",
    "game_gbc": "Game Boy Color",
    "game_gba": "Game Boy Advance",
    "game_nes": "Nintendo Entertainment System",
    "game_snes": "Super Nintendo",
    "game_n64": "Nintendo 64",
    "game_nds": "Nintendo DS",
    "game_genesis": "Mega Drive",
    "game_gamegear": "Game Gear",
    "game_mastersystem": "Master System",
    "game_atari2600": "Atari 2600",
    "game_atari5200": "Atari 5200",
    "game_atari7800": "Atari 7800",
    "game_atari800": "Atari 800",
    "game_atari_lynx": "Atari Lynx",
    "game_ngpc": "Neo Geo Pocket Color",
    "game_pokemonmini": "Pokemon Mini",
    "game_sega32x": "Sega 32X",
    "game_virtualboy": "Virtual Boy",
    "game_wonderswan": "WonderSwan Color",
}

USER_AGENT = "romm-cover-sync/1.0"


def log(message: str) -> None:
    print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}", flush=True)


def imported_filenames(work: Path) -> set[str]:
    """Filenames that already have a curated cover from the bulk import."""
    names: set[str] = set()
    platforms = work / "platforms"
    if not platforms.is_dir():
        return names
    for jsonl in platforms.glob("*.jsonl"):
        with jsonl.open(encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if entry.get("cover"):
                    names.add(entry["filename"])
    return names


def fetch_json(url: str, api_key: str, timeout: int) -> dict:
    request = urllib.request.Request(
        url,
        headers={
            "X-API-Key": api_key,
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.load(response)


def download_image(url: str, timeout: int) -> bytes:
    request = urllib.request.Request(
        url,
        headers={"Accept": "image/*", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read()


def to_webp(data: bytes) -> bytes:
    with Image.open(io.BytesIO(data)) as image:
        image = image.convert("RGB")
        image.thumbnail((512, 512), Image.LANCZOS)
        buffer = io.BytesIO()
        image.save(buffer, "WEBP", quality=82, method=4)
        return buffer.getvalue()


def write_state(path: Path, state: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    tmp.replace(path)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-url", default="https://comunidad.respaldame.org")
    parser.add_argument("--api-key", default=os.environ.get("COMMUNITY_API_KEY"))
    parser.add_argument("--work", default="/srv/roms/game-import")
    parser.add_argument("--input", help="read the game list from a local JSON instead of the API")
    parser.add_argument("--limit", type=int, help="process only the first N games")
    parser.add_argument("--force", action="store_true", help="download even when the URL did not change")
    parser.add_argument(
        "--include-imported",
        action="store_true",
        help="also download games that already have a curated import cover",
    )
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    work = Path(args.work)
    covers = work / "covers"
    covers.mkdir(parents=True, exist_ok=True)
    state_path = work / "remote-games.json"

    state: dict = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            log("WARN: remote-games.json is not valid JSON, starting from scratch")

    if args.input:
        payload = json.loads(Path(args.input).read_text(encoding="utf-8"))
    else:
        if not args.api_key:
            log("ERROR: no API key (use --api-key or COMMUNITY_API_KEY)")
            return 2
        url = args.api_url.rstrip("/") + "/api/rclone/game-covers"
        try:
            payload = fetch_json(url, args.api_key, args.timeout)
        except urllib.error.HTTPError as error:
            if error.code == 404:
                log("WARN: the game-covers endpoint is not deployed yet; skipping")
                return 0
            log(f"ERROR: {url}: HTTP {error.code}")
            return 1

    games = payload.get("games") or []
    if args.limit:
        games = games[: args.limit]

    imported = imported_filenames(work)
    downloaded = skipped = errors = 0
    seen: set[str] = set()

    for game in games:
        filename = (game.get("filename") or "").strip()
        if not filename:
            continue
        seen.add(filename)

        platform = CONTENT_TYPE_PLATFORMS.get(game.get("contentType") or "")
        if not platform:
            skipped += 1
            continue
        if filename in imported and not args.include_imported:
            skipped += 1
            continue

        poster = (game.get("posterUrl") or "").strip()
        if not poster:
            skipped += 1
            continue
        if poster.startswith("/"):
            poster = args.api_url.rstrip("/") + poster

        previous = state.get(filename)
        if (
            previous
            and previous.get("sourceUrl") == poster
            and (covers / previous.get("cover", "")).is_file()
            and not args.force
        ):
            skipped += 1
            continue

        try:
            webp = to_webp(download_image(poster, args.timeout))
            name = f"{hashlib.sha256(webp).hexdigest()[:24]}.webp"
            target = covers / name
            if not target.exists():
                target.write_bytes(webp)
            state[filename] = {
                "platform": platform,
                "title": game.get("title") or None,
                "year": game.get("year") or None,
                "cover": name,
                "sourceUrl": poster,
                "updatedAt": int(time.time()),
            }
            downloaded += 1
        except Exception as error:  # a broken cover must not stop the batch
            errors += 1
            log(f"WARN {filename}: {error}")

    # Only a complete API response can be trusted to prune removed games.
    if not args.input and not args.limit and len(games) >= 1000:
        for filename in list(state):
            if filename not in seen:
                del state[filename]

    write_state(state_path, state)
    log(
        f"covers: {len(games)} listed, {downloaded} downloaded, "
        f"{skipped} skipped, {errors} errors, {len(state)} in state"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
