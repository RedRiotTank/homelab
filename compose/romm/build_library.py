#!/usr/bin/env python3
"""
Genera una biblioteca compatible con RomM a partir de:
  - el catalogo de usenet-community (/src/platforms/*.jsonl)
  - las caratulas locales (/normalized/<plataforma>/media/covers o /src/covers)
  - el montaje rclone (/media/Juegos/Retro/<plataforma>)

Salida:
  <out>/<slug_romm>/<juego>       -> symlink a /mnt/media/Juegos/Retro/...
  <out>/<slug_romm>/gamelist.xml
  <out>/<slug_romm>/covers/<stem>.png

Se ejecuta dentro del contenedor rommapp/romm (ya trae Python + Pillow).
El host /opt/compose/romm/library se monta en /out.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from xml.etree.ElementTree import Element, ElementTree, SubElement

from PIL import Image

# carpeta normalizada (nombre visible) -> (slug RomM, nombre visible)
PLATFORMS: dict[str, tuple[str, str]] = {
    "Game Boy": ("gb", "Game Boy"),
    "Game Boy Color": ("gbc", "Game Boy Color"),
    "Game Boy Advance": ("gba", "Game Boy Advance"),
    "Nintendo Entertainment System": ("nes", "Nintendo Entertainment System"),
    "Super Nintendo": ("snes", "Super Nintendo"),
    "Nintendo 64": ("n64", "Nintendo 64"),
    "Nintendo DS": ("nds", "Nintendo DS"),
    "Mega Drive": ("genesis", "Mega Drive"),
    "Master System": ("mastersystem", "Master System"),
    "Game Gear": ("gamegear", "Game Gear"),
    "Atari 2600": ("atari2600", "Atari 2600"),
    "Atari 5200": ("atari5200", "Atari 5200"),
    "Atari 7800": ("atari7800", "Atari 7800"),
    "Atari 800": ("atari800", "Atari 800"),
    "Atari Lynx": ("lynx", "Atari Lynx"),
    "Neo Geo Pocket Color": ("neo-geo-pocket-color", "Neo Geo Pocket Color"),
    "Virtual Boy": ("virtualboy", "Virtual Boy"),
    "WonderSwan Color": ("wonderswan-color", "WonderSwan Color"),
    "Pokemon Mini": ("pokemon-mini", "Pokemon Mini"),
    "Sega 32X": ("sega32", "Sega 32X"),
}

# BIOS/accesorios que no tienen sentido como "juego" en RomM
SKIP = {"Fukutake StudyBox", "Otros"}

# El nombre de la carpeta en el catalogo de comunidad no siempre coincide con
# el de la carpeta normalizada (NES se llama "Nintendo Entertainment System").
RCLONE_FOLDERS = {
    "Nintendo Entertainment System": "NES",
}

ROM_EXTENSIONS = {
    ".gb", ".gbc", ".gba", ".nes", ".fds", ".unf", ".unh", ".sfc", ".smc",
    ".n64", ".z64", ".v64", ".nds", ".md", ".gen", ".smd", ".gg", ".sms",
    ".a26", ".a52", ".a78", ".atr", ".xex", ".xfd", ".cas", ".lnx", ".lyx",
    ".ngp", ".ngc", ".min", ".32x", ".vb", ".ws", ".wsc", ".bin",
}

IGNORE_NAMES = {
    "covers", "media", "screenshots", "marquees", "wheels", "images",
    "gamelist.xml", "manifest.json",
}

INVALID_XML = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def clean_title(stem: str) -> str:
    value = re.sub(r"\[[^\]]*\]", " ", stem)
    value = re.sub(r"\([^)]*\)", " ", value)
    value = value.replace("_", " ").strip()
    return re.sub(r"\s+", " ", value) or stem


def xml_text(value: object | None) -> str:
    return INVALID_XML.sub("", str(value or ""))


def cover_destination(
    display: str,
    stem: str,
    cover_hash: str | None,
    out_dir: Path,
    normalized_root: Path,
    covers_src: Path,
    force: bool,
) -> str | None:
    target = out_dir / "covers" / f"{stem}.png"
    if target.exists() and not force:
        return f"./covers/{target.name}"

    # Preferir el WebP ya optimizado (512 px): evita abrir y redimensionar el
    # PNG original de 700x700, que es lo que hacia el build lento.
    source: Path | None = None
    if cover_hash:
        candidate = covers_src / f"{cover_hash}.webp"
        if candidate.exists():
            source = candidate
    if source is None:
        original = normalized_root / display / "media" / "covers" / f"{stem}.png"
        if original.exists():
            source = original
    if source is None:
        return None

    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with Image.open(source) as image:
            image = image.convert("RGB")
            image.thumbnail((512, 512), Image.LANCZOS)
            # compress_level bajo: el build de 9k caratulas pesa mas que el
            # tamano final; RomM reescala y guarda su propia copia.
            image.save(target, "PNG", compress_level=1)
        return f"./covers/{target.name}"
    except Exception as error:  # una caratula rota no debe parar el lote
        print(f"  AVISO caratula {source}: {error}", file=sys.stderr)
        return None


def build_platform(
    display: str,
    args: argparse.Namespace,
    src: Path,
    normalized: Path,
    roms_root: Path,
    roms_target: str,
    out: Path,
) -> int:
    slug = PLATFORMS[display][0]
    rclone_folder = RCLONE_FOLDERS.get(display, display)
    source_dir = roms_root / "Juegos" / "Retro" / rclone_folder
    slug_dir = out / slug
    slug_dir.mkdir(parents=True, exist_ok=True)
    (slug_dir / "covers").mkdir(parents=True, exist_ok=True)

    metadata: dict[str, dict] = {}
    jsonl = src / "platforms" / f"{display}.jsonl"
    if jsonl.exists():
        with jsonl.open(encoding="utf-8") as handle:
            for line in handle:
                if line.strip():
                    entry = json.loads(line)
                    metadata[entry["filename"]] = entry

    source_files: list[str] = []
    if source_dir.is_dir():
        for entry in os.scandir(source_dir):
            if entry.name in IGNORE_NAMES:
                continue
            if not Path(entry.name).suffix.lower() in ROM_EXTENSIONS:
                continue
            if entry.is_file(follow_symlinks=True):
                source_files.append(entry.name)
    source_files.sort()

    root = Element("gameList")
    count = 0
    covers = 0

    for filename in source_files:
        hit = metadata.get(filename, {})
        stem = Path(filename).stem
        target = slug_dir / filename
        try:
            if target.is_symlink() or target.exists():
                target.unlink()
            target.symlink_to(f"{roms_target}/Juegos/Retro/{rclone_folder}/{filename}")
        except OSError as error:
            print(f"  AVISO enlace {filename}: {error}", file=sys.stderr)
            continue

        cover = cover_destination(
            display, stem, hit.get("cover"), slug_dir, normalized,
            src / "covers", args.force_covers,
        )
        if cover:
            covers += 1

        game = SubElement(root, "game")
        SubElement(game, "path").text = f"./{filename}"
        SubElement(game, "name").text = xml_text(
            hit.get("title") or clean_title(stem)
        )
        if hit.get("overview"):
            SubElement(game, "desc").text = xml_text(hit["overview"])
        year = hit.get("year")
        if isinstance(year, int):
            SubElement(game, "releasedate").text = f"{year:04d}0101T000000"
        if hit.get("developer"):
            SubElement(game, "developer").text = xml_text(hit["developer"])
        if hit.get("publisher"):
            SubElement(game, "publisher").text = xml_text(hit["publisher"])
        if hit.get("genres"):
            SubElement(game, "genre").text = xml_text(hit["genres"])
        if cover:
            SubElement(game, "cover").text = cover
        count += 1

    tree = ElementTree(root)
    tree.write(slug_dir / "gamelist.xml", encoding="utf-8", xml_declaration=True)

    pruned_links = pruned_covers = 0
    if args.prune:
        keep_files = set(source_files)
        keep_covers = {f"{Path(name).stem}.png" for name in source_files}
        for entry in os.scandir(slug_dir):
            if entry.is_symlink() and entry.name not in keep_files:
                Path(entry.path).unlink(missing_ok=True)
                pruned_links += 1
        covers_dir = slug_dir / "covers"
        if covers_dir.is_dir():
            for entry in os.scandir(covers_dir):
                if entry.is_file() and entry.name not in keep_covers:
                    Path(entry.path).unlink(missing_ok=True)
                    pruned_covers += 1

    extra = f", -{pruned_links} enlaces, -{pruned_covers} caratulas" if args.prune else ""
    print(f"{display:42s} -> {slug:25s} {count:5d} juegos, {covers:5d} caratulas{extra}")
    return count


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--src", default="/src", help="directorio game-import")
    parser.add_argument("--normalized", default="/normalized", help="ROMs normalizadas")
    parser.add_argument("--roms-root", default="/media", help="raiz del montaje para listar")
    parser.add_argument("--roms-target", default="/mnt/media", help="ruta de los symlinks dentro de RomM")
    parser.add_argument("--out", default="/out/library", help="raiz de la biblioteca RomM")
    parser.add_argument("--platforms", default="", help="lista separada por comas (nombre visible)")
    parser.add_argument("--clean", action="store_true", help="borra la salida antes de generar")
    parser.add_argument("--prune", action="store_true", help="borra symlinks y caratulas huerfanos")
    parser.add_argument("--force-covers", action="store_true", help="reconvierte caratulas existentes")
    args = parser.parse_args()

    src = Path(args.src)
    normalized = Path(args.normalized)
    roms_root = Path(args.roms_root)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    if args.platforms:
        selected = [p.strip() for p in args.platforms.split(",") if p.strip()]
    else:
        selected = [p for p in PLATFORMS if p not in SKIP]

    total = 0
    for display in selected:
        if display not in PLATFORMS:
            print(f"AVISO: plataforma desconocida {display}", file=sys.stderr)
            continue
        if args.clean:
            slug = PLATFORMS[display][0]
            import shutil
            shutil.rmtree(out / slug, ignore_errors=True)
        total += build_platform(
            display, args, src, normalized, roms_root, args.roms_target, out
        )
    print(f"TOTAL: {total} juegos")


if __name__ == "__main__":
    main()
