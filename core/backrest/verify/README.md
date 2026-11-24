# Backrest restore verification

`backrest-verify` is a small sidecar that runs a monthly restore drill against the
Backrest/Restic repositories. It restores the latest Core snapshot from the local
repository and from one rotating remote repository, verifies the restored files,
validates the database dumps and the staged configuration, and exposes the
result on the internal monitoring network.

It does **not** mount the Docker socket and never writes to a repository:
repositories are mounted read-only and every Restic command uses `--no-lock`.

## Schedule

- Day **16** of each month at **04:00 Europe/Madrid**.
- Even months restore from `GDrive-RedServer`; odd months from `miixzify`
  (`BACKREST_VERIFY_REMOTE_ROTATION`).
- The local repository is restored every month.
- On failure the drill retries after `BACKREST_VERIFY_RETRY_HOURS` (24 h) up to
  `BACKREST_VERIFY_MAX_RETRIES` times, then waits for the next month.

## Build and run

```bash
docker build -t backrest-verify:local .

# One manual run, local repository only, no HeavyData
docker run --rm --network monitoring \
  -e BACKREST_EXPORTER_PASSWORD=... \
  -v backrest_config:/config:ro \
  -v /srv/backups:/repos/external:ro \
  -v /home/deployer/.config/rclone:/rclone:ro \
  -v /var/tmp/backrest-verify:/verify/scratch \
  -v backrest_verify_data:/verify/state \
  backrest-verify:local --run-now --repos local-repo-srv --skip-heavy
```

The normal deployment is the `backrest-verify` service in the parent Compose
file. It is attached to the `monitoring` network and has no published ports.

Scratch space defaults to `/var/tmp/backrest-verify` on the root filesystem, not
to `/srv`, so the restore does not compete with the Restic repository and the
bulk data disk. It needs roughly 40 GiB free; the service aborts if
`BACKREST_VERIFY_MIN_FREE_GB` is not met.

For a quick validation without restoring every file, limit the Core restore
paths:

```bash
--paths /data,/backup/homelab,/backup/opt/core,\
/backup/docker_volumes/backrest_config,\
/backup/docker_volumes/npm_data,\
/backup/docker_volumes/headscale_data,\
/backup/docker_volumes/npm_letsencrypt
```

This still runs every validation and is useful after changing the hook or the
check logic. The monthly schedule always restores the full snapshot.

## What it validates

1. `restic check --read-data-subset=10%` for every repository.
2. Snapshot freshness (default 36 h) and path coverage.
3. Full `restic restore --verify` of the Core snapshot.
4. `sha256sum` manifest of the staged configuration.
5. Gzip, SQLite integrity, PostgreSQL `pg_restore --list` and dump markers for
   the logical database dumps.
6. Stack `.env` files, Telegram Alertmanager config, SSH keys, host-config
   whitelist, Compose YAML, Headscale config and Komodo environment.
7. Vaultwarden keys, NPM and Headscale SQLite databases, NPM TLS certificates.
8. HeavyData restore from the selected remote repository: Nextcloud user files,
   Minecraft servers and AppFlowy MinIO data.

The exact list is visible in `status.json` under `checks`.

## Status and metrics

- `GET /status` — JSON result and per-check details.
- `GET /metrics` — Prometheus metrics.
- `GET /healthz` — liveness.
- `reports/report-*.md` — human-readable report, retained according to
  `BACKREST_VERIFY_KEEP_REPORTS`.

Reports and status live in the `backrest_verify_data` volume. The writable
`rclone.conf` copy lives in the container's `/tmp` and is never persisted.

## Troubleshooting

- **`preflight:disk` fails** — free space in `HOST_BACKREST_VERIFY_SCRATCH_DIR`.
- **`preflight:rclone` fails** — `HOST_RCLONE_CONFIG_DIR` is not mounted or has no
  `rclone.conf`.
- **`repo_check` fails** — run the same command manually:
  `restic -r <uri> --no-lock check --read-data-subset=10%`.
- **`snapshot:*` fails** — the latest snapshot is stale or a plan path was
  removed. Check the Backrest plan.
- **`manifest` fails** — the staged config in the snapshot does not match its
  manifest. Re-run the `collect-config.sh` hook and take a fresh backup.
- **A drill is already running** — the lock file is `run.lock`; a stale process
  releases it when it exits. Use `--run-now` only when no scheduled drill is
  running.
