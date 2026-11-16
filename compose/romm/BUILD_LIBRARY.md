# Biblioteca RomM desde el rclone de comunidad

RomM no puede leer las caratulas del rclone porque **no estan dentro del montaje**:
el montaje `community:` solo expone las ROMs. Las caratulas viven en la app de
comunidad y se sirven por `/api/covers/<hash>.webp`.

La solucion es generar una capa local compatible con RomM:

```text
/opt/compose/romm/library/
  gba/
    Juego.gba        -> symlink a /mnt/media/Juegos/Retro/Game Boy Advance/Juego.gba
    gamelist.xml      -> titulo, año, descripcion, genero, cover...
    covers/Juego.png  -> caratula local
```

RomM lee `gamelist.xml` + `covers/` y el validador de rutas de RomM permite
symlinks. El compose monta:

- `/opt/compose/romm/library` -> `/romm/library/roms`
- `/mnt/media` -> `/mnt/media` (para que resuelvan los symlinks)

## Generar / actualizar

El generador usa `/srv/roms/game-import` (manifest/caratulas de la importacion
de comunidad) y el montaje rclone. Se ejecuta con la imagen de RomM, que ya
trae Python y Pillow:

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

Importante: montar el catalogo en `/catalog`, **no en `/src`**, porque `/src`
es el codigo y el venv de la imagen de RomM.

Para probar una sola plataforma:

```bash
... --platforms "Atari 800"
```

## Podar juegos borrados

Cuando un juego desaparece del catalogo, sus symlinks y caratulas quedan
huerfanos. `--prune` los elimina y regenera el `gamelist.xml` sin reconvertir
las caratulas que siguen existiendo:

```bash
... --out /out/library --prune
```

Es el modo normal para actualizar la biblioteca tras borrar juegos. `--clean`
solo hace falta para reconstruir desde cero.

## Reescaneo programado

RomM no ve los cambios del montaje por si solo: su biblioteca es el arbol
generado. Para que un escaneo programado sirva de algo, hay que podar antes:

```text
build_library.py --prune  ->  escaneo Quick de RomM
```

La programacion **no va en este repositorio**: cada servidor la define en su
propio `.env` (`ENABLE_SCHEDULED_RESCAN`, `SCHEDULED_RESCAN_CRON`) y, si quiere
podar automaticamente, en su propio cron/systemd. Los valores por defecto del
compose son reescaneo desactivado y `0 3 * * *`.

Ejemplo de cron de usuario para podar antes del escaneo:

```cron
45 7 * * 4 /ruta/al/romm-library-sync.sh >> /ruta/al/log 2>&1
```

## Configuracion de RomM

Copiar `config.example.yml` a `${RETRO_DATA_DIR}/config/config.yml` (o dejar el
que ya existe) y reiniciar RomM. Lo importante:

- `filesystem.skip_hash_calculation: true`
- prioridad `gamelist` para metadata y artwork
- `scan.media: [box2d]`
- sin `SCREENSCRAPER_USER/PASSWORD` en el entorno

## Escanear

1. Entrar en RomM.
2. Escanear con **Gamelist** como unico proveedor (o todos; con ScreenScraper
   desactivado solo queda gamelist).
3. El primer escaneo copia las caratulas a `resources/roms/{platform}/{rom}/cover/`.

## Notas

- Si se reinicia el montaje rclone (`rclone-media.service`), el bind FUSE del
  contenedor puede quedar en "Socket not connected". Reiniciar RomM despues:
  `docker restart romm`.
- Las plataformas usan los slugs oficiales de RomM: `gb`, `gbc`, `gba`, `nes`,
  `snes`, `n64`, `nds`, `genesis`, `mastersystem`, `gamegear`, `atari2600`,
  `atari5200`, `atari7800`, `atari800`, `lynx`, `neo-geo-pocket-color`,
  `virtualboy`, `wonderswan-color`, `pokemon-mini`, `sega32`.
- `Fukutake StudyBox` (BIOS) y `Otros` se omiten.
