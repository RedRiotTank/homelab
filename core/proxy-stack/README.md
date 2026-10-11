# Proxy Stack (Nginx Proxy Manager + Cloudflare DDNS)

Edge routing and dynamic DNS infrastructure for the homelab. This stack manages public reverse proxying, Let's Encrypt SSL/TLS certificates, and automated Cloudflare DNS synchronization.

## Architecture & Design Decisions

### Native Docker Volumes

To ensure maximum portability and prevent file permission issues, this stack uses **native Docker volumes** instead of host bind mounts for its database (`npm_data`) and certificates (`npm_letsencrypt`).

### Traffic Flow

```text
             [ External Traffic ]              [ Internal / Tailscale Traffic ]
                      │                                       │
                      │ (Ports 80/443)                        ▼
                      │                              [ AdGuard Home DNS ]
                      │                              (Rewrites domain to Local IP)
                      ▼                                       │
+-------------------------------------------------------------▼-+
|                        PROXY STACK                            |
|                                                               |
|    [Cloudflare DDNS]            [Nginx Proxy Manager]         |
|            │                              │      │            |
+------------│------------------------------│------│------------+
             │                              │      │
 (Updates IP)│             (Routes Traffic) │      │ (Ships Logs)
             ▼                              ▼      ▼
       [Cloudflare]                   [proxy_net] [monitoring_net]
                                            │      │
                                            ▼      ▼
                                  [Homelab Backend Services]
```

### Split DNS + Access Lists as a Combined Security Model

Exposing services directly to the public internet is risky. Rather than relying on a single control, this stack combines two independent techniques so that private services never touch the public internet path, while still presenting valid, trusted TLS certificates to internal clients:

- **Split DNS** (via [AdGuard Home](../adguard/README.md)) makes internal/VPN clients resolve homelab domains straight to the private IP of the host running this proxy, avoiding hairpin NAT and keeping LAN/VPN traffic off the WAN entirely.
- **NPM Access Lists** act as a second, independent layer at the proxy itself: even if a public DNS record exists (needed for Let's Encrypt issuance or intentionally public hosts), requests arriving from non-private source IPs are rejected with `403 Forbidden` before reaching the backend.

Both controls are detailed in [Specific Notes](#specific-notes) below.

## Service Interconnections & Dependencies

- [adguard](../adguard/README.md) — provides the Split DNS rewrites that route internal/Tailscale clients directly to this stack instead of through public DNS.
- [monitoring-stack-gpnc](../monitoring-stack-gpnc/README.md) — consumes container logs shipped by Promtail over the external `monitoring_net` network (actual Docker network name: `monitoring`), attached via `docker-compose.override.yml`.
- **Virtually every other service in this repository** — headscale, komodo, backrest, and any future web service — joins this stack's external `proxy_net` network to be reverse-proxied and TLS-terminated by Nginx Proxy Manager. This stack must be deployed first, since `proxy_net` is the shared ingress network all other stacks expect to already exist.

## File Structure

| Path | Purpose |
| --- | --- |
| `docker-compose.yml` | Core service definitions: `nginx-proxy` (NPM) and `cloudflare-ddns`. Portable, infrastructure-agnostic. |
| `docker-compose.override.yml` | Attaches both services to the external `monitoring_net` and injects Promtail logging labels. Optional. |
| `.env.example` | Template for Cloudflare credentials and NPM port bindings. |
| `theme-manager/` | Standalone, **not yet integrated** utility (see below). |

### About `theme-manager/`

This directory contains a small standalone Node.js HTTP server (`server.js`) plus a static dashboard (`dashboard.html`) for managing custom NPM error pages (403/404). It exposes a toggle API (`GET /api/themes/:type`, `POST /api/toggle`) that reads/writes a `themes.json` file per error type and serves theme assets from a `/themes` directory under `/custom_error/`.

**This utility is currently not wired into `docker-compose.yml`** — there is no Dockerfile, no service entry, and no volume connecting it to NPM's custom pages directory. It is present in the repository as a standalone tool only. To actually use it, you would need to run it yourself (e.g., `node theme-manager/server.js`) and manually point its `/themes` base directory at the same location NPM serves custom error pages from — no such wiring exists yet in this repo.

## Configuration & Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `CF_API_TOKEN` | _(required)_ | Cloudflare API token with `Zone - DNS - Edit` permission, used by `cloudflare-ddns` to keep DNS records current. |
| `CF_ZONE` | `example.com` | The Cloudflare DNS zone to update. |
| `CF_PROXIED` | `false` | Whether Cloudflare should proxy (orange-cloud) the record instead of DNS-only. |
| `CF_CRON` | `*/5 * * * *` | Schedule for IP-check/update runs. |
| `NPM_HTTP_PORT` | `80` | Host port for HTTP (also used for Let's Encrypt HTTP-01 challenges). |
| `NPM_HTTPS_PORT` | `443` | Host port for HTTPS. |
| `NPM_ADMIN_PORT` | `81` | Host port for the NPM admin UI. |

## Deployment & Operational Commands

### Prerequisites

1. Create the shared external ingress network (only needed once per host):

   ```bash
   docker network create proxy_net
   ```

2. Obtain a Cloudflare API Token with `Zone - DNS - Edit` permission for `CF_API_TOKEN`.

### The Override Layer

`docker-compose.override.yml` attaches both services to `monitoring_net` for log shipping to [monitoring-stack-gpnc](../monitoring-stack-gpnc/README.md). It is entirely optional:

- **Komodo Users:** Omit `docker-compose.override.yml` from the "File Paths" configuration if the monitoring stack is not deployed.
- **CLI Users:** Delete the override file, or run explicitly with `docker compose -f docker-compose.yml up -d`.

### Option A: GitOps via Komodo (Recommended)

1. Add this repository to your Komodo instance.
2. Set the environment variables in the Komodo UI based on the `.env.example` structure.
3. In "File Paths", list both `docker-compose.yml` and `docker-compose.override.yml` (if using monitoring).
4. Click Deploy.

### Option B: Manual CLI Deployment

1. Copy and populate the environment variables:

   ```bash
   cp .env.example .env
   nano .env
   ```

2. Start the stack:

   ```bash
   docker compose up -d
   ```

### Post-Deployment Verification

- Check container health: `docker compose ps`
- Tail logs: `docker compose logs -f nginx-proxy cloudflare-ddns`
- Confirm the DDNS container successfully resolved and updated the Cloudflare record in its logs before relying on it.

### Default Credentials (NPM First Boot)

If this is a fresh installation with an empty `npm_data` volume, use the default credentials to access the admin portal on port `81`:

- **Email:** `admin@example.com`
- **Password:** `changeme` _(You will be forced to update these upon initial login.)_

## Specific Notes

### Split DNS via AdGuard Home

Instead of internal traffic going out to the public internet and bouncing back (hairpin NAT), configure AdGuard to resolve your domains locally:

- Go to your [AdGuard Home](../adguard/README.md) dashboard.
- Navigate to **Filters -> DNS Rewrites**.
- Add a rewrite for your domain (e.g., `*.example.com`) pointing directly to the **private internal IP** of the server hosting this proxy stack (e.g., `192.168.1.X`).
- _Result:_ When you are on your local network or connected via Tailscale, traffic flows directly to the server, never touching the public internet.

### NPM Access Lists (Whitelisting)

To block public access to your private services, use Nginx Proxy Manager's **Access Lists**:

- In NPM, go to **Access Lists** and create one named "Private Local & VPN Only".
- Under the **Access** tab, set `allow` rules for your private subnets (e.g., `192.168.1.0/24` for LAN, `100.64.0.0/10` for Tailscale).
- Apply this Access List to your private proxy hosts.
- _Result:_ If someone tries to access your service from a public IP, NPM will block them with a `403 Forbidden` error, but you will still access it seamlessly and securely with a valid SSL certificate.
