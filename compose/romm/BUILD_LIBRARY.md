# RomM library from the community rclone mount

RomM cannot read the rclone covers because **they are not inside the mount**:
the `community:` mount only exposes the ROMs. Covers live in the community app
and are served at `/api/covers/<hash>.webp`.

The solution is to generate a local layer that RomM understands:

```text
/opt/compose/romm/library/
  gba/
    Game.gba          -> symlink to /mnt/media/Juegos/Retro/Game Boy Advance/Game.gba
    gamelist.xml      -> title, year, description, genre, cover...
    covers/Game.png   -> local cover
```

RomM reads `gamelist.xml` + `covers/`, and its path validator allows symlinks.
The compose file mounts:

- `/opt/compose/romm/library` -> `/romm/library/roms`
- `/mnt/media` -> `/mnt/media` (so the symlinks resolve)

## Build / update

The builder uses `/srv/roms/game-import` (manifest/covers from the community
import) and the rclone mount. It runs with the RomM image, which already ships
Python and Pillow:

```bash
docker run --rm --entrypoint sh \
  -v /home/deployer/homelab/compose/romm:/work:ro \
  -v /srv/roms/game-import:/catalog:ro \
  -v /srv/roms/normalized:/normalized:ro \
  -v /mnt/media:/media:ro \
  -v /opt/compose/romm:/out \
  rommapp/romm:latest \
  -c '/src/.venv/bin/python /work/build_library.py \
        --src /catalog --normalized /normalized \
        --roms-root /media --roms-target /mnt/media \
        --out /out/library --clean'
```

Important: mount the catalog at `/catalog`, **not at `/src`**, because `/src`
is the RomM image code and virtualenv.

To test a single platform:

```bash
... --platforms "Atari 800"
```

## Prune deleted games

When a game disappears from the catalog, its symlinks and covers are left
behind. `--prune` removes them and regenerates `gamelist.xml` without
re-encoding the covers that still exist:

```bash
... --out /out/library --prune
```

This is the normal mode for updating the library after deleting games. `--clean`
is only needed for a full rebuild from scratch.

## Covers for games uploaded outside the bulk import

Games uploaded through the normal path (web upload or a plain `rclone copy`)
get their metadata and cover from the classifier (RAWG today, ScreenScraper or
another provider later). The app stores the cover as a URL in `nzbs.poster_url`,
not as a local file, so that cover is **not** in the rclone mount and RomM would
show a placeholder.

`sync_covers.py` fixes that. It asks the community for the classified cover list
(`GET /api/rclone/game-covers`), downloads every cover that is not already in
the bulk-import catalog, converts it to a 512 px WebP and stores it next to the
import covers:

```text
/srv/roms/game-import/covers/<hash>.webp
/srv/roms/game-import/remote-games.json   (filename -> platform/title/year/cover)
```

`build_library.py` reads `remote-games.json` and uses it for the games that have
no normalized manifest entry. Curated import metadata always wins.

Run it before the prune:

```bash
docker run --rm --entrypoint sh \
  -e COMMUNITY_API_KEY=... \
  -v /home/deployer/homelab/compose/romm:/work:ro \
  -v /srv/roms/game-import:/catalog \
  rommapp/romm:latest \
  -c '/src/.venv/bin/python /work/sync_covers.py \
        --api-url https://comunidad.respaldame.org --work /catalog'
```

It is incremental: a cover whose URL did not change is skipped, and games that
already have a curated import cover are ignored. The provider does not matter:
whatever URL the classifier wrote is what gets mirrored locally.

## Scheduled rescan

RomM does not notice changes in the mount by itself: its library is the
generated tree. For a scheduled scan to be useful, sync covers and prune first:

```text
sync_covers.py -> build_library.py --prune -> RomM quick scan
```

The schedule **does not belong in this repository**: each server defines it in
its own `.env` (`ENABLE_SCHEDULED_RESCAN`, `SCHEDULED_RESCAN_CRON`) and, if it
wants automatic pruning, in its own cron/systemd. The compose defaults are
rescan disabled and `0 3 * * *`.

Example user cron entry to prune before the scan:

```cron
45 7 * * 4 /path/to/romm-library-sync.sh >> /path/to/log 2>&1
```

## RomM configuration

Copy `config.example.yml` to `${RETRO_DATA_DIR}/config/config.yml` (or keep the
existing one) and restart RomM. The important parts:

- `filesystem.skip_hash_calculation: true`
- `gamelist` priority for metadata and artwork
- `scan.media: [box2d]`
- no `SCREENSCRAPER_USER/PASSWORD` in the environment

## Scan

1. Open RomM.
2. Scan with **Gamelist** as the only provider (or all of them; with ScreenScraper
   disabled, only gamelist remains).
3. The first scan copies the covers to `resources/roms/{platform}/{rom}/cover/`.

## Notes

- If the rclone mount is restarted (`rclone-media.service`), the container's
  FUSE bind can end up in "Socket not connected". Restart RomM afterwards:
  `docker restart romm`.
- Platforms use the official RomM slugs: `gb`, `gbc`, `gba`, `nes`,
  `snes`, `n64`, `nds`, `genesis`, `mastersystem`, `gamegear`, `atari2600`,
  `atari5200`, `atari7800`, `atari800`, `lynx`, `neo-geo-pocket-color`,
  `virtualboy`, `wonderswan-color`, `pokemon-mini`, `sega32`.
- `Fukutake StudyBox` (BIOS) and `Otros` are skipped.
