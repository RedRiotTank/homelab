# Pterodactyl

Self-hosted game server management platform, powered by [Pterodactyl](https://pterodactyl.io): a web **Panel** for provisioning, configuring, and administering game servers, backed by **Wings**, the node daemon that actually talks to Docker to create, start, stop, and monitor each game server's container. This stack runs both halves — Panel and Wings — on the same host (`CrimsonServer`), making that host a self-contained Pterodactyl node.

## Architecture & Design Decisions

The stack is four containers: **panel** (web UI/API, PHP+nginx, bundles its own cron scheduler and queue worker via the image's internal supervisord — no separate sidecar container is needed), **database** (MariaDB, the Panel's sole datastore), **cache** (Redis, used for the Panel's cache/session/queue drivers), and **wings** (the node daemon).

```text
     [ Admins / Users ]                [ Nginx Proxy Manager ]              [ panel ]              [ database ]
     (browser, HTTPS)      ───────▶    (TLS termination)        proxy_net  (PHP+nginx,  ────────▶  (MariaDB,
                                                                             cron+queue              panel state)
                                                                             built-in)   ────────▶  [ cache ]
                                                                                                     (Redis)
     [ Game clients ]                                                          │ control-plane calls
     (connect to game                                                          ▼ (HTTPS :8080, SFTP :2022,
      server ports directly,           [ wings ]  ───/var/run/docker.sock───▶  host Docker daemon
      not through NPM)                 (node daemon,                           │
                                        published :8080/:2022)                  ▼
                                                                        [ game server containers ]
                                                                        (spawned by Wings as siblings
                                                                         on the host, not nested)
```

### Why Wings isn't just another container on `proxy_net`

Wings' daemon API (`:8080`) terminates its own TLS and is reached directly — by the Panel, and by admins' browsers for the live console/file-manager websocket — rather than through Nginx Proxy Manager. Its SFTP port (`:2022`) is raw TCP and NPM (HTTP/HTTPS only) cannot proxy it at all. Both ports are published straight to the host in `docker-compose.yml` instead of living behind `proxy_net`, matching [upstream Wings' own example](https://github.com/pterodactyl/wings/blob/develop/docker-compose.example.yml).

### Why Wings needs `/var/run/docker.sock`, not Docker-in-Docker

Wings does not run game servers inside itself. It is handed the **host's** Docker socket and uses it to create game-server containers as siblings on the host's own Docker daemon — the same daemon this entire stack runs under. That's why `WINGS_DATA_DIR` and `WINGS_TMP_DIR` are bind-mounted **host-path-to-itself** (e.g. `/opt/compose/pterodactyl/wings/data:/opt/compose/pterodactyl/wings/data`) rather than remapped to a tidier in-container path like the other volumes: when Wings bind-mounts a server's files into a new sibling container, it passes the *host* path, so the path it sees inside its own container must be byte-for-byte identical to what the host (and therefore the sibling container) sees. Get this wrong and server installs/boots fail with confusing "no such file or directory" errors even though the files are plainly present. See [Specific Notes](#specific-notes) before changing these paths.

### No queue/cron sidecar

Unlike some community compose files, this stack does not run a separate `panel-cron` or `panel-worker` container. The official `ghcr.io/pterodactyl/panel` image already runs nginx, PHP-FPM, `artisan queue:work`, and `artisan schedule:run` (the Laravel scheduler, invoked every minute) together under its own internal supervisord. Do not scale the `panel` service beyond one replica — the bundled scheduler has no leader election, so a second replica would duplicate every scheduled task.

## Service Interconnections & Dependencies

- **[proxy-stack](../../core/proxy-stack/README.md)** — Nginx Proxy Manager terminates TLS and routes `APP_URL` to the `panel` container over the shared external `proxy_net` network, attached via `docker-compose.override.yml`. Wings is **not** attached to `proxy_net` — see [Architecture & Design Decisions](#architecture--design-decisions).
- **[monitoring-stack-gpnc](../../core/monitoring-stack-gpnc/README.md)** — all four containers ship logs to the central Promtail/Loki pipeline via the external `monitoring_net` network (actual Docker network name: `monitoring`), attached through `docker-compose.override.yml`.
- **[backrest](../../core/backrest/README.md)** — all persistent state lives under host bind mounts at `/opt/compose/pterodactyl/**`, which falls inside Backrest's `HOST_OPT_DIR` (`/opt`) backup source; no additional Backrest plan path is required, but verify it isn't caught by any exclusion rule. Game-server data itself can grow large — consider whether `WINGS_DATA_DIR` belongs in the "Bulk / Heavy Data" backup tier described in Backrest's README rather than the daily "Configs & State" tier.
- **[komodo](../../core/komodo/README.md)** — intended to be the normal way this stack is deployed/redeployed on `CrimsonServer`, via [komodo-periphery](../../core/komodo-periphery/README.md) running on that node.

## File Structure

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | Base, portable service definitions for `panel`, `database`, `cache`, and `wings` — image, environment, bind-mounted volumes, and the two ports Wings must publish directly. No ingress or observability network attachment. |
| `docker-compose.override.yml` | Attaches `panel` to **both** `proxy_net` (ingress) and `monitoring_net` (logging); attaches `database`, `cache`, and `wings` to `monitoring_net` only. Injects Promtail logging labels on all four. **Not optional** — this file is required for the Panel to be reachable at all, since `proxy_net` lives here instead of the base file. |
| `.env.example` | Template for every environment variable consumed by both compose files. |

> **Consistent with `core/` convention:** like [vaultwarden](../../core/vaultwarden/README.md) and [adguard](../../core/adguard/README.md), `proxy_net` lives in the override, not the base `docker-compose.yml` — the base file stays infrastructure-agnostic. If the monitoring stack isn't deployed on `CrimsonServer`, don't omit the whole override — instead edit it to drop the four `monitoring_net` entries and their `logging*` labels, keeping `proxy_net` on `panel`.

## Configuration & Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `PANEL_VERSION` / `WINGS_VERSION` | `latest` | Image tags for the Panel and Wings. |
| `MARIADB_VERSION` | `11` | Image tag for the database. |
| `REDIS_VERSION` | `alpine` | Image tag for the cache. |
| `TZ` | `Europe/Madrid` | Container timezone; also sets the Panel's `APP_TIMEZONE`. |
| `APP_URL` | _(required)_ | Full HTTPS URL the Panel is reached at; must match the Nginx Proxy Manager host entry. |
| `APP_SERVICE_AUTHOR` | _(required)_ | Contact address shown in system emails and support links. |
| `TRUSTED_PROXIES` | `*` | IPs/CIDRs trusted to set `X-Forwarded-*` headers; safe as `*` since `proxy_net` has no other ingress path. |
| `DB_DATABASE` | `panel` | MariaDB database name. |
| `DB_USERNAME` | `pterodactyl` | MariaDB application user. |
| `DB_PASSWORD` | _(required)_ | Password for `DB_USERNAME`. Generate with `openssl rand -base64 32`. |
| `DB_ROOT_PASSWORD` | _(required)_ | MariaDB root password. Generate with `openssl rand -base64 32`. |
| `HASHIDS_LENGTH` | `8` | Length of generated public hashids for servers/nodes/users. |
| `MAIL_DRIVER` | `log` | `log` writes mail to the Panel's log (no SMTP needed); set to `smtp` and fill in the remaining `MAIL_*` vars to send real email. |
| `MAIL_FROM`, `MAIL_HOST`, `MAIL_PORT`, `MAIL_USERNAME`, `MAIL_PASSWORD`, `MAIL_ENCRYPTION` | see `.env.example` | SMTP settings, only used when `MAIL_DRIVER=smtp`. |
| `PANEL_PORT` | `127.0.0.1:8081` | Unused by default (the matching `ports:` line in `docker-compose.yml` is commented out). Only relevant for local/debug access before `proxy_net` is wired up. |
| `WINGS_UID` / `WINGS_GID` / `WINGS_USERNAME` | `988` / `988` / `pterodactyl` | Identity Wings runs as; also owns files under `WINGS_DATA_DIR`. |
| `WINGS_API_PORT` | `8080` | Published host port for the Wings daemon API/console websocket (Wings' own TLS). |
| `WINGS_SFTP_PORT` | `2022` | Published host port for SFTP file access to game servers. |
| `DATABASE_DATA_DIR` | `/opt/compose/pterodactyl/database/data` | Host bind mount for MariaDB data files. |
| `CACHE_DATA_DIR` | `/opt/compose/pterodactyl/cache/data` | Host bind mount for Redis persistence. |
| `PANEL_VAR_DIR` | `/opt/compose/pterodactyl/panel/var` | Host bind mount for the Panel's runtime state (`/app/var`). |
| `PANEL_NGINX_DIR` | `/opt/compose/pterodactyl/panel/nginx` | Host bind mount for custom nginx vhost snippets (`/etc/nginx/http.d`). |
| `PANEL_CERTS_DIR` | `/opt/compose/pterodactyl/panel/certs` | Host bind mount for `/etc/letsencrypt`; generally unused behind NPM (no in-container Let's Encrypt flow is configured here), kept for parity with upstream's layout. |
| `PANEL_LOGS_DIR` | `/opt/compose/pterodactyl/panel/logs` | Host bind mount for Panel application logs. |
| `WINGS_ETC_DIR` | `/opt/compose/pterodactyl/wings/etc` | Host bind mount for `/etc/pterodactyl` (`config.yml`). |
| `WINGS_DATA_DIR` | `/opt/compose/pterodactyl/wings/data` | **Host-path-to-itself** bind mount for all game-server files. Must exactly match `system.data` in `config.yml`. See [Specific Notes](#specific-notes). |
| `WINGS_LOGS_DIR` | `/opt/compose/pterodactyl/wings/logs` | Host bind mount for Wings daemon logs. |
| `WINGS_TMP_DIR` | `/opt/compose/pterodactyl/wings/tmp` | **Host-path-to-itself** bind mount used for transient server-install containers. See [Specific Notes](#specific-notes). |
| `WINGS_RUN_DIR` | `/opt/compose/pterodactyl/wings/run` | Host bind mount for Wings' internal runtime socket directory. |

## Deployment & Operational Commands

### 1. Prerequisite Setup on CrimsonServer

Create the host directories backing every bind mount before first deploy:

```bash
sudo mkdir -p /opt/compose/pterodactyl/{database/data,cache/data}
sudo mkdir -p /opt/compose/pterodactyl/panel/{var,nginx,certs,logs}
sudo mkdir -p /opt/compose/pterodactyl/wings/{etc,data,logs,tmp,run}
sudo chown -R 988:988 /opt/compose/pterodactyl/wings/data /opt/compose/pterodactyl/wings/tmp
```

(`988:988` matches the default `WINGS_UID`/`WINGS_GID` — adjust if you changed those.)

Confirm the host's Docker Engine supports memory/swap cgroup accounting, since this is what Pterodactyl uses to enforce each game server's memory limit:

```bash
docker info | grep -i "swap limit"
```

If you see `WARNING: No swap limit support`, memory limits on game servers will be silently unenforced. On standard Debian/Ubuntu x86_64 this is enabled by default; it mainly affects minimal kernels (e.g. Raspberry Pi OS), where you'd add `cgroup_enable=memory swapaccount=1` to the kernel command line and reboot.

Create the shared external networks if they don't already exist on this host (normally created once by [proxy-stack](../../core/proxy-stack/README.md) and [monitoring-stack-gpnc](../../core/monitoring-stack-gpnc/README.md)):

```bash
docker network create proxy_net
```

### 2. Deploy

**Option A: GitOps via Komodo (Recommended)**

1. Add this repository to your Komodo instance, targeting the `komodo-periphery` agent running on `CrimsonServer`.
2. Set every environment variable listed above in the Komodo UI's Stack environment editor — see the summary at the end of this document for the exact list to populate.
3. In **File Paths**, list **both** `docker-compose.yml` and `docker-compose.override.yml` — the override is required since it carries the `proxy_net` attachment.
4. Click Deploy.

**Option B: Manual CLI Deployment (on CrimsonServer)**

```bash
cp .env.example .env
nano .env
docker compose up -d
```

Compose automatically merges `docker-compose.override.yml` on top of `docker-compose.yml`, so a plain `docker compose up -d` picks up both — running `-f docker-compose.yml` alone leaves `panel` off `proxy_net` and unreachable via the reverse proxy.

### 3. Run Database Migrations & Create the First Admin User

The Panel image runs pending migrations automatically on container start. If you ever need to run them manually (e.g. after a manual schema change), or to create the first administrator account, exec into the running `panel` container:

```bash
docker compose exec panel php artisan migrate --seed --force
docker compose exec panel php artisan p:user:make
```

`p:user:make` prompts interactively for email, username, password, and whether the account is a root administrator — answer yes for the first account.

### 4. Create a Node and Pair Wings

1. In the Panel web UI, go to **Admin → Locations** and create at least one location.
2. Go to **Admin → Nodes → Create New** and configure it for `CrimsonServer`:
   - **FQDN**: a domain/IP Wings is reachable at (the node's `WINGS_API_PORT`, not routed through NPM — see [Architecture & Design Decisions](#architecture--design-decisions)).
   - **Communicate Over SSL**: enabled (Wings serves its own certificate on `:8080`).
   - **Daemon Server File Directory**: set to the exact value of `WINGS_DATA_DIR` (default `/opt/compose/pterodactyl/wings/data`).
   - **Daemon SFTP Port**: matches `WINGS_SFTP_PORT` (default `2022`).
3. Save the node, then open its **Configuration** tab. The Panel displays an auto-deploy command containing a one-time token — adapt it to run against this stack's `wings` container instead of a bare `docker run`, so it writes `config.yml` into the bind-mounted `WINGS_ETC_DIR`:

   ```bash
   docker compose run --rm --no-deps wings \
     configure --panel-url "$APP_URL" --token <token-from-panel> --node <node-id>
   ```

4. Start (or restart) Wings so it picks up the freshly written config:

   ```bash
   docker compose up -d wings
   ```

5. Back in the Panel's **Configuration** tab, confirm the node shows as online. If it doesn't, check `docker compose logs -f wings` first — a mismatch between `WINGS_DATA_DIR` here and "Daemon Server File Directory" on the node is the most common cause of servers failing to install afterward even when the node itself connects fine.

### 5. Verify

```bash
docker compose logs -f panel wings
```

Visit `APP_URL` to confirm the Panel login page loads, log in with the admin account created above, and confirm the node created in step 4 shows an online status indicator.

### Post-Deployment Access

- **Panel Web UI:** exclusively via [Nginx Proxy Manager](../../core/proxy-stack/README.md), proxying to the container name `panel` on port `80`.
- **Wings Daemon API / Console:** `https://<CrimsonServer-FQDN>:${WINGS_API_PORT}`, reached directly by the Panel and by admin browsers for the live console — not proxied by NPM.
- **SFTP File Access:** `sftp://<CrimsonServer-FQDN>:${WINGS_SFTP_PORT}`, per-server credentials shown in each server's Panel page.

## Specific Notes

### The `WINGS_DATA_DIR` / `WINGS_TMP_DIR` path-matching requirement

These two variables appear **twice** on their respective volume lines in `docker-compose.yml` (`${WINGS_DATA_DIR}:${WINGS_DATA_DIR}`), not once mapped to a different in-container path like every other mount in this stack. This is intentional: Wings uses the mounted `/var/run/docker.sock` to talk to the **host's** Docker daemon directly and spawn game-server containers as siblings of itself, passing *host* filesystem paths for their bind mounts. If the path Wings writes to inside its own container doesn't match the real host path byte-for-byte, the sibling containers Wings creates won't see the files it just wrote. If you change either variable from its default, you must also update the Node's **Daemon Server File Directory** setting in the Panel UI (for `WINGS_DATA_DIR`) before regenerating `config.yml`, and re-create the matching host directory with correct ownership before redeploying.

### First Admin Account & Hardening

1. Create the first administrator via `p:user:make` as shown above — there's no setup wizard in the web UI itself.
2. Treat `DB_PASSWORD`, `DB_ROOT_PASSWORD`, and the Wings pairing token as credentials on par with any other root secret — store them in Komodo's environment variables, not in a committed `.env` file (see [.gitignore](../../.gitignore)).
3. Consider enabling two-factor authentication on the admin account from **Account Settings → Security** inside the Panel.

### Game Server Ports

Each game server you create gets its own port allocation (configured per-Node under **Admin → Nodes → Allocations**, then assigned per-server). Those ports are published directly on `CrimsonServer` by the individual server containers Wings creates — they are independent of, and in addition to, `WINGS_API_PORT`/`WINGS_SFTP_PORT`, and need their own firewall/NAT rules opened on the host as you allocate them.
