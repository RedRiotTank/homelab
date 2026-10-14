# AdGuard Home

Network-wide ad-blocking and privacy-preserving DNS server. AdGuard Home is the core routing brain for the homelab's Split-Brain DNS architecture, resolving internal domains differently depending on whether a client is on the physical LAN or connected over the Tailscale/Headscale VPN mesh.

## Architecture & Design Decisions

To ensure maximum portability and prevent file permission issues, this stack uses **native Docker volumes** for its database (`adguard_work`) and configuration file (`adguard_conf`) instead of host bind mounts.

Setup and local web UI ports (`ADGUARD_SETUP_PORT`, `ADGUARD_WEB_PORT`) are bound to `127.0.0.1` only. This is a deliberate failsafe: the primary access path for the dashboard is through [Nginx Proxy Manager](../proxy-stack/README.md) over `proxy_net`, not a direct host port. The loopback bindings exist purely for emergency/local access (e.g. via SSH tunnel) and to prevent unauthorized LAN exposure of the admin UI. DNS itself (port 53, TCP/UDP) remains open on the host since it must be reachable by LAN and VPN clients.

```text
             [ VPN / Tailscale Traffic ]       [ Local LAN Traffic ]
                      │                                  │
      (Original IP: 100.64.0.X hidden by Docker)         │
                      ▼                                  │
              [ Docker Gateway ]                 (Original IP Kept)
               (IP: 172.20.0.1)                          │
                      │                                  │
+---------------------▼----------------------------------▼--------------------+
|                         ADGUARD HOME STACK                                |
|                                                                           |
|                  [ Custom Filtering Rules Engine ]                        |
|                                                                           |
|   Rule 1: If IP is 172.20.0.1           Rule 2: If IP is NOT 172.20.0.1   |
|   Rewrite to VPN Tunnel (100.64.0.1)    Rewrite to Host IP (192.168.1.X)  |
|                                                                           |
+---------------------┬----------------------------------┬--------------------+
                      │                                  │
                      ▼                                  ▼
           [ Routes via Headscale ]           [ Routes via Physical LAN ]
                      │                                  │
                      +------------------+---------------+
                                         │
                                         ▼
                   [ Nginx Proxy Manager (proxy_net) ]
```

## Service Interconnections & Dependencies

- **[headscale](../headscale/README.md)** — VPN clients registered on the Headscale control server send DNS queries that arrive at AdGuard Source-NAT'd by the Docker gateway. Headscale's `config.yaml` should point its global nameserver at this stack's tunnel IP to enable MagicDNS resolution.
- **[proxy-stack](../proxy-stack/README.md)** — Nginx Proxy Manager performs the actual TLS-terminated routing to backend services, reached over the shared external `proxy_net` network, attached through `docker-compose.override.yml`. AdGuard Home's web UI is itself exposed through this proxy.
- **[monitoring-stack-gpnc](../monitoring-stack-gpnc/README.md)** — Container logs are shipped to the central Promtail/Loki pipeline via the external `monitoring_net` Docker network (actual network name: `monitoring`), attached through `docker-compose.override.yml`.

## File Structure

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | Base, portable service definition (image, volumes, DNS/web ports). No network attachment — not reachable through the reverse proxy on its own. |
| `docker-compose.override.yml` | Attaches the container to `proxy_net` (ingress) and `monitoring_net` (logging), and injects Promtail labels. **Not optional** — `proxy_net` lives here instead of the base file, so the dashboard isn't reachable via Nginx Proxy Manager without it. |
| `.env.example` | Template for port-binding environment variables. |

## Configuration & Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `ADGUARD_DNS_PORT` | `53` | DNS listener port (TCP/UDP), must stay reachable from LAN/VPN clients. |
| `ADGUARD_SETUP_PORT` | `127.0.0.1:3030` | First-run setup wizard, loopback-only failsafe access. |
| `ADGUARD_WEB_PORT` | `127.0.0.1:8053` | Main dashboard, loopback-only failsafe access (primary access is via reverse proxy). |

## Deployment & Operational Commands

### 1. Disable the `systemd-resolved` Port 53 Listener (Host Machine)

By default, Ubuntu/Debian's systemd binds to port 53. Free it up before deploying:

```bash
sudo sed -r -i.orig 's/#?DNSStubListener=yes/DNSStubListener=no/g' /etc/systemd/resolved.conf
sudo systemctl restart systemd-resolved
```

### 2. Create External Networks

Create the shared external ingress network if it does not already exist (typically managed by the [Proxy Stack](../proxy-stack/README.md)):

```bash
docker network create proxy_net
```

### 3. Deploy

**Option A: GitOps via Komodo (Recommended)**

1. Add this repository to your Komodo instance.
2. Set the environment variables in the Komodo UI based on the `.env.example` structure.
3. In "File Paths", list **both** `docker-compose.yml` and `docker-compose.override.yml` — the override carries the `proxy_net` attachment, so it's required for the dashboard to be reachable via the reverse proxy. If the monitoring stack isn't deployed, edit the override to drop the `monitoring_net` entry and the two `logging*` labels rather than omitting the file.
4. Click Deploy.

**Option B: Manual CLI Deployment**

```bash
cp .env.example .env
nano .env
docker compose up -d
```

Compose automatically merges `docker-compose.override.yml` on top of `docker-compose.yml`, so a plain `docker compose up -d` picks up both — running `-f docker-compose.yml` alone leaves the container off `proxy_net` and unreachable via the reverse proxy.

### 4. Verify

```bash
docker compose logs -f adguardhome
```

Then check **Query Log** in the AdGuard UI to confirm DNS requests are being received and resolved as expected.

### Post-Deployment Access

- **Initial Setup Wizard:** via local SSH tunnel on port `3030` (`http://localhost:3030`).
- **Main Dashboard:** securely via [Nginx Proxy Manager](../proxy-stack/README.md) using the container name `adguardhome` on port `80`, or locally via port `8053`. Both interfaces are bound to `127.0.0.1` on the host to prevent unauthorized LAN access.

## Specific Notes

### Split-Brain DNS (The SNAT Workaround)

To achieve a true **Split-Brain DNS** without exposing the proxy to the public internet, clients need different IP resolutions for the same domain (`*.example.com`).

Because AdGuard runs inside the `proxy_net` Docker network, UDP DNS queries coming from [Headscale](../headscale/README.md) VPN clients (`100.64.x.x`) are Source-NAT'd (SNAT) by the Docker gateway. AdGuard sees these requests as coming from the Docker network gateway (e.g., `172.20.0.1`) rather than the actual Tailscale IP.

**The Solution:** DO NOT use the standard "DNS Rewrites" tab, as it overrides everything globally. Instead, use **Custom Filtering Rules** in the AdGuard UI (`Filters -> Custom filtering rules`) to exploit the SNAT behavior:

```
! 1. If the client is Docker/Tailscale SNAT (172.20.0.1), return the VPN tunnel IP
||yourdomain.com^$client=172.20.0.1,dnsrewrite=100.64.0.1

! 2. For everyone else (e.g., physical LAN clients), return the physical host IP
||yourdomain.com^$client=~172.20.0.1,dnsrewrite=192.168.1.182
```

_(Replace `yourdomain.com` and the IPs with your actual environment values. If the Split-DNS breaks after a Docker network recreation, check the AdGuard Query Log to see if the `172.20.0.1` gateway IP has shifted to a different subnet.)_
