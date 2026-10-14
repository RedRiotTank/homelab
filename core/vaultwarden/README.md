# Vaultwarden

Self-hosted, lightweight implementation of the Bitwarden password-manager server API, powered by [Vaultwarden](https://github.com/dani-garcia/vaultwarden). This stack is the credential vault for the homelab and its users: it stores encrypted logins, notes, cards, and identities, and serves the official Bitwarden web, browser-extension, and mobile clients.

## Architecture & Design Decisions

Vaultwarden uses a **host bind mount** (`./vw-data`), not a named Docker volume, so the SQLite database, attachments, and RSA key pair are trivially visible/restorable from the host filesystem and sit inside the directory tree already covered by [backrest](../backrest/README.md)'s `HOST_HOMELAB_DIR` backup source — no extra backup source needs to be registered for this stack.

The container publishes no host port at all — `docker-compose.yml` has no `ports:` mapping, only a commented-out one for local/debug use. It's reached exclusively through [Nginx Proxy Manager](../proxy-stack/README.md) over the container network, via the `proxy_net` attachment carried in `docker-compose.override.yml` (see [File Structure](#file-structure) for why that differs from other `core/` stacks). Real-time sync (new/changed items pushed instantly to unlocked clients) relies on Vaultwarden's built-in WebSocket notifications hub, served on the same port as the web vault — the reverse proxy just needs WebSocket upgrade support enabled on the proxy host entry, not a separate port or container.

The `/admin` diagnostics and user-management panel is gated behind `ADMIN_TOKEN` rather than disabled outright, so day-two operations (inviting/deleting users, checking server diagnostics) stay available without exposing them to anyone without the token.

```text
  [ Bitwarden Clients ]                 [ Nginx Proxy Manager ]                [ Vaultwarden ]
  (Browser ext, mobile,        HTTPS    (TLS termination,        proxy_net     (Rocket web server
   desktop, CLI)           ───────────▶  WebSocket upgrade)   ─────────────▶   + notifications hub)
                                                                                      │
                                                                                      ▼
                                                                          ./vw-data (bind mount)
                                                                          db.sqlite3, attachments/,
                                                                          rsa_key*, icon_cache/
```

## Service Interconnections & Dependencies

- **[proxy-stack](../proxy-stack/README.md)** — Nginx Proxy Manager performs TLS-terminated routing to the container, reached over the shared external `proxy_net` network. Enable the **Websockets Support** toggle on the proxy host entry so the `/notifications/hub` endpoint works for live sync.
- **[monitoring-stack-gpnc](../monitoring-stack-gpnc/README.md)** — Container logs are shipped to the central Promtail/Loki pipeline via the external `monitoring_net` Docker network (actual network name: `monitoring`), attached through `docker-compose.override.yml`.
- **[backrest](../backrest/README.md)** — Because `vw-data` lives as a bind mount inside this repository's directory tree, it's already captured read-only by Backrest's `HOST_HOMELAB_DIR` source; no additional Backrest plan path is required, but verify it isn't caught by any exclusion rule.

## File Structure

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | Base, portable service definition (image, environment, bind-mounted data volume). No network attachment and no published port — not reachable on its own. |
| `docker-compose.override.yml` | Attaches the container to **both** `proxy_net` (ingress) and `monitoring_net` (logging) and injects Promtail logging labels. **Not optional** — this file is required for the service to be reachable at all, since `proxy_net` lives here instead of the base file. |
| `.env.example` | Template for all environment variables consumed by `docker-compose.yml`. |

> **Consistent with the rest of `core/`:** like [adguard](../adguard/README.md), [backrest](../backrest/README.md), [headscale](../headscale/README.md), and [komodo](../komodo/README.md), `proxy_net` lives in the override here, not the base `docker-compose.yml` — the base file stays fully network-agnostic. [proxy-stack](../proxy-stack/README.md) is the sole exception, since NPM being on `proxy_net` is its core function rather than an optional cross-stack add-on. If the monitoring stack isn't deployed on this host, don't omit the whole override — instead edit it to drop the `monitoring_net` entry and the two `logging*` labels, keeping `proxy_net`.

## Configuration & Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `VAULTWARDEN_DOMAIN` | _(required)_ | Full HTTPS URL clients use to reach this instance; must match the reverse-proxy domain for icons, email links, and WebAuthn/Passkeys to work correctly. |
| `SIGNUPS_ALLOWED` | `false` | Allow new account registration. Recommended to flip to `false` once all accounts are created. |
| `ADMIN_TOKEN` | _(required)_ | Secures the `/admin` panel. Generate with `openssl rand -base64 48`. |
| `VAULTWARDEN_PORT` | `127.0.0.1:8083` | Unused by default (the `ports:` mapping in `docker-compose.yml` is commented out). Only relevant if you uncomment that line for local/debug access. |
| `VAULTWARDEN_DATA_DIR` | `./vw-data` | Host bind-mount path for the SQLite database, attachments, and RSA keys. |
| `TZ` | `Europe/Madrid` | Container timezone, used for log timestamps. |

## Deployment & Operational Commands

### 1. Create External Networks

Create the shared external ingress network if it does not already exist (typically managed by the [Proxy Stack](../proxy-stack/README.md)):

```bash
docker network create proxy_net
```

### 2. Deploy

**Option A: GitOps via Komodo (Recommended)**

1. Add this repository to your Komodo instance.
2. Set the environment variables in the Komodo UI based on the `.env.example` structure.
3. In "File Paths", list **both** `docker-compose.yml` and `docker-compose.override.yml` — unlike other `core/` stacks, the override is required here since it carries the `proxy_net` attachment. If the monitoring stack isn't deployed, edit the override to drop the `monitoring_net` entry/labels rather than omitting the file (see [File Structure](#file-structure)).
4. Click Deploy.

**Option B: Manual CLI Deployment**

```bash
cp .env.example .env
nano .env
docker compose up -d
```

Compose automatically merges `docker-compose.override.yml` on top of `docker-compose.yml`, so a plain `docker compose up -d` picks up both — running `-f docker-compose.yml` alone leaves the container with no network attachment and no proxy access.

### 3. Verify

```bash
docker compose logs -f vaultwarden
```

Then visit `VAULTWARDEN_DOMAIN` to confirm the web vault loads, and `VAULTWARDEN_DOMAIN/admin` (prompting for `ADMIN_TOKEN`) to confirm the admin panel is reachable.

### Post-Deployment Access

- **Web Vault:** exclusively via [Nginx Proxy Manager](../proxy-stack/README.md), proxying to the container name `vaultwarden` on port `80`. No host port is published by default.
- **Admin Panel:** `<VAULTWARDEN_DOMAIN>/admin`, authenticated with `ADMIN_TOKEN`.
- **Bitwarden Clients:** point any official Bitwarden app/extension at `VAULTWARDEN_DOMAIN` as a self-hosted server before logging in or creating the first account.

## Specific Notes

### WebSocket Notifications

Vaultwarden serves live-sync notifications on the same port as the web vault (no separate `3012` port or container needed with recent images). In Nginx Proxy Manager, enable **Websockets Support** on the proxy host entry for this domain — without it, clients still work but fall back to periodic polling instead of instant sync.

### First-Run Hardening

1. Deploy with `SIGNUPS_ALLOWED=true`, create the account(s) you need, then redeploy with `SIGNUPS_ALLOWED=false`.
2. Treat `ADMIN_TOKEN` like any other root credential — store it in Komodo's environment variables, not in a committed `.env` file (see [.gitignore](../../.gitignore)).
3. Consider enabling two-factor authentication (TOTP/WebAuthn) on every account from the vault's own **Settings → Security** page; Vaultwarden supports this out of the box without additional configuration here.
