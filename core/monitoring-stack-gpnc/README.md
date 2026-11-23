# Monitoring Stack (GPNC)

*Based on the original [docker-monitoring-stack-gpnc](https://github.com/ruanbekker/docker-monitoring-stack-gpnc) by Ruan Bekker.*

The central observability backbone for the homelab: metrics collection (Prometheus, cAdvisor, Node Exporter), log aggregation (Loki, Promtail), alerting (Alertmanager, Uncomplicated Alert Receiver), caching (Redis), and visualization (Grafana). Every other stack in this repository ships its logs here and, for remote nodes, exposes metrics endpoints this stack pulls from. Domains, versions, and resource limits are extracted to environment variables to keep the stack portable across hosts.

## Architecture & Design Decisions

```text
                         ┌─────────────────────────────┐
                         │           Grafana           │
                         │  (dashboards + datasources) │
                         └───────┬─────────┬───────────┘
                                 │         │        │
                   reads         │         │        │ reads
             ┌───────────────────┘         │        └───────────────────┐
             ▼                             ▼                            ▼
    ┌───────────────────┐           ┌───────────────────┐          ┌───────────────────┐
    │    Prometheus     │           │   Alertmanager    │          │       Loki        │
    │  (metrics TSDB)   │──alerts──>│ (routing/notify)  │          │  (log storage)    │
    └───────┬───────────┘           └─────────┬─────────┘          └─────────┬─────────┘
            │ scrapes (pull)                  │ default route                │ receives (push)
   ┌────────┴─────────┐              ┌────────▼───────────┐           ┌──────┴───────────┐
   ▼                  ▼              │ uncomplicated-     │           ▼                  ▼
[node-exporter]   [cadvisor]         │ alert-receiver     │     [promtail]      [other stacks' Promtail
   (local)          (local)          │ (webhook UI)       │      (local docker    sidecars via override,
                                     └────────────────────┘        containers)     e.g. adguard, backrest,
   ▼                  ▼                                                            headscale, proxy-stack,
[node-exporter]   [cadvisor]  ◄── over the private network ─── monitoring-agent-gpnc on remote/edge nodes
 (remote node)    (remote node)
```

### Shared `monitoring` network

All services here join a single Docker network literally named `monitoring`, created by this stack's own `docker-compose.yml` (not `external`, since this is the owning stack — other stacks reference it as an external network, usually named `monitoring_net`).

Despite the name, joining `monitoring`/`monitoring_net` is **not** what makes Promtail or Prometheus pick up another stack's container:

- **Promtail** discovers every container through the mounted Docker socket (`docker_sd_configs` in `configs/promtail/promtail.yaml`) and reads its log files straight off disk — it never talks to the target container over the network. What actually routes a container's logs correctly is the `logging` / `logging_jobname` **labels**, not network membership.
- **Prometheus** only scrapes the exact targets listed in `configs/prometheus/prometheus.yml` (`prometheus`, `alertmanager`, `node-exporter`, `cadvisor`, local and the remote-node targets over Tailscale). It never scrapes adguard, backrest, vaultwarden, headscale, komodo, or any other app container, regardless of which network they're on.

So for other stacks in this repository, attaching to `monitoring_net` is effectively decorative for telemetry purposes — harmless to keep (e.g. useful for `docker exec <container> curl http://loki:3100/ready` while debugging), but it is the `logging`/`logging_jobname` labels alone that make Promtail ship a container's logs, not the network attachment.

This stack **does** ship its own `docker-compose.override.yml`, but for a different reason than everyone else's: it attaches `grafana` (only) to `proxy_net`, so the dashboard can be reverse-proxied by [proxy-stack](../proxy-stack/README.md) under a custom domain instead of, or in addition to, its direct host port. `prometheus`, `alertmanager`, `redis`, and the rest intentionally stay off `proxy_net` — see [Configuration & Environment Variables](#configuration--environment-variables) for their loopback-binding options instead.

> **Deployment path:** the compose file bind-mounts `./configs/...` and `./dashboards/...`. Clone the stack to a host directory that is accessible to the Docker daemon, or adjust the bind paths in the compose file for your own layout.

### Pull metrics locally, pull metrics remotely, push logs everywhere

Metrics use a pull model: Prometheus scrapes `node-exporter` and `cadvisor` on the local host directly, and *also* scrapes remote/edge-node exporters listed in local target files under `configs/prometheus/targets/`. Those files are not committed because they normally contain private hostnames or IP addresses; see [`configs/prometheus/targets/README.md`](configs/prometheus/targets/README.md). The default scrape and evaluation interval is **30 s**; lower it in `configs/prometheus/prometheus.yml` only if you need finer resolution. [monitoring-agent-gpnc](../monitoring-agent-gpnc/README.md) is the lightweight agent deployed on those remote nodes. Logs use the opposite model: Promtail instances (local, and the ones bundled into most other stacks via their override layer) push log streams into Loki.

### Alerting defaults to a safe no-op channel

Alertmanager's active config (`configs/alertmanager/alertmanager-fallback-config.yml`) routes every alert to `uncomplicated-alert-receiver`, a simple webhook-based viewer, so the stack is usable out of the box without any third-party notification credentials. Four additional ready-to-use templates for real channels (Slack, Email, Opsgenie, Pushover) ship alongside it — see [Specific Notes](#specific-notes).

### Externally managed data volumes

Unlike most stacks in this repository (which declare their own named volumes), `grafana-data`, `prometheus-data`, and `loki-data` are declared `external: true`, parameterized via `GRAFANA_DATA_VOLUME`, `PROMETHEUS_DATA_VOLUME`, and `LOKI_DATA_VOLUME` (defaulting to `monitoring-stack-gpnc_grafana-data`, etc.). Docker Compose will **not** create these automatically — they must already exist (from a prior deployment) or be created manually before the first `up`. This is a deliberate guard against accidentally recreating/losing the stack's historical metrics and dashboards state when the compose project is redeployed or renamed. See [Deployment & Operational Commands](#deployment--operational-commands).

### Consistent labeling via YAML anchors

The compose file defines `x-logging` and `x-common-labels` anchors applied to every service, guaranteeing uniform JSON-file log rotation (`max-size: 1m`, `max-file: 1`) and consistent Promtail-discovery labels (`logging: promtail`, `logging_jobname: monitoring`, `stackname: docker-monitoring-stack-gpnc`) without repeating configuration per service.

## Service Interconnections & Dependencies

This is the stack every other service ships telemetry to. Services that attach to the shared `monitoring`/`monitoring_net` Docker network via their own `docker-compose.override.yml`:

- [adguard](../adguard/README.md) — ships container logs via Promtail labels.
- [backrest](../backrest/README.md) — ships container logs via Promtail labels.
- [headscale](../headscale/README.md) — ships container logs via Promtail labels.
- [proxy-stack](../proxy-stack/README.md) — ships container logs via Promtail labels; also the other direction of this relationship — this stack's own `docker-compose.override.yml` attaches `grafana` to proxy-stack's external `proxy_net` network, so the dashboard can be reverse-proxied under a custom domain.
- [tailscale-client](../tailscale-client/README.md) — labels only (runs in `network_mode: host`, so it cannot join `monitoring_net`; labels are still read by the local Promtail instance on that host).
- [komodo](../komodo/README.md) — joins both `proxy_net` and `monitoring_net` via its own committed `docker-compose.override.yml`.
- [monitoring-agent-gpnc](../monitoring-agent-gpnc/README.md) — remote/edge-node counterpart; its `node-exporter`/`cadvisor` are scraped by this stack's Prometheus over the private network, and its Promtail pushes logs directly to this stack's Loki via `LOKI_URL`.

## File Structure

```text
monitoring-stack-gpnc/
├── docker-compose.yml        # grafana, prometheus, cadvisor, node-exporter,
│                              # alertmanager, uncomplicated-alert-receiver, redis, loki, promtail
├── docker-compose.override.yml # optional: attaches grafana to proxy_net for reverse-proxy ingress
├── .env.example               # versions, domains, resource limits, optional port bindings
├── Makefile                   # make up / clean / logs / open shortcuts
├── LICENSE                    # original MIT license (Ruan Bekker)
├── configs/
│   ├── grafana/provisioning/  # datasources.yml, dashboards.yml
│   ├── prometheus/            # prometheus.yml, recording-rules.yml, alerting-rules.yml
│   ├── alertmanager/          # fallback + slack/email/opsgenie/pushover templates
│   ├── promtail/              # promtail.yaml (local docker log scrape config)
│   └── loki/                  # loki.yaml, rules.yaml
└── dashboards/
    ├── node-metrics.json
    ├── container-metrics.json
    └── log-search.json
```

## Configuration & Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `GRAFANA_VERSION` | `12.0.0` | Grafana image tag. |
| `PROMETHEUS_VERSION` | `v2.42.0` | Prometheus image tag. |
| `CADVISOR_VERSION` | `v0.46.0` | cAdvisor image tag. |
| `NODE_EXPORTER_VERSION` | `v1.5.0` | Node Exporter image tag. |
| `ALERTMANAGER_VERSION` | `v0.25.0` | Alertmanager image tag. |
| `REDIS_VERSION` | `6` | Redis image tag. |
| `GRAFANA_ROOT_URL` | `https://monitoring.yourdomain.com/` | Must match the public/reverse-proxy URL for correct OAuth/link generation. |
| `GRAFANA_DOMAIN` | `monitoring.yourdomain.com` | Used for `GF_SERVER_DOMAIN`. |
| `MONITORING_CPUS` | `0.5` | Per-service CPU limit (applied uniformly). |
| `MONITORING_MEM_LIMIT` | `512m` | Default memory limit for the stack. |
| `PROMETHEUS_MEM_LIMIT` | `1g` | Prometheus-specific memory limit; overrides `MONITORING_MEM_LIMIT` for the Prometheus container. |
| `ALERTMANAGER_CONFIG_FILE` | `./configs/alertmanager/alertmanager-fallback-config.yml` | Alertmanager config mounted at `/etc/alertmanager/config.yml`. Point it at a private file to use Telegram or email. |
| `GRAFANA_PORT` / `PROMETHEUS_PORT` / `ALERTMANAGER_PORT` / `ALERT_RECEIVER_PORT` / `REDIS_PORT` | `127.0.0.1:<port>` | Host bindings for management ports. Keep them on loopback when running behind [proxy-stack](../proxy-stack/README.md). |
| `LOKI_PORT` | `3100` | Loki push/query port. It must be reachable from every Promtail instance; restrict access with a private network or firewall. |
| `GRAFANA_DATA_VOLUME` / `PROMETHEUS_DATA_VOLUME` / `LOKI_DATA_VOLUME` | `monitoring-stack-gpnc_grafana-data` / `..._prometheus-data` / `..._loki-data` | Names of the pre-existing **external** volumes (see prerequisite below). |
| `PROMETHEUS_TARGETS_DIR` | `./configs/prometheus/targets` | Host directory mounted at `/etc/prometheus/targets` for remote scrape targets. Point it outside the repo to keep private addresses out of Git. |

## Deployment & Operational Commands

### 1. Create the external data volumes (prerequisite)

Because `grafana-data`, `prometheus-data`, and `loki-data` are declared `external: true`, Compose will fail with a "volume not found" error unless they already exist:

```bash
docker volume create monitoring-stack-gpnc_grafana-data
docker volume create monitoring-stack-gpnc_prometheus-data
docker volume create monitoring-stack-gpnc_loki-data
```

Skip this step only if these volumes already exist from a previous deployment, or if you've set custom names via `GRAFANA_DATA_VOLUME`/`PROMETHEUS_DATA_VOLUME`/`LOKI_DATA_VOLUME` and created those instead.

### 2. Configure environment variables

```bash
cp .env.example .env
nano .env
```

Ensure `GRAFANA_DOMAIN` and `GRAFANA_ROOT_URL` are correctly set to match your reverse proxy configuration.

### 3. Optional: reverse-proxy ingress for Grafana

`docker-compose.override.yml` attaches `grafana` to the external `proxy_net` network so it can sit behind [proxy-stack](../proxy-stack/README.md) instead of, or alongside, its direct host port. This is the only service affected — the rest of the stack is unaffected either way.

- **Using it:** make sure `proxy_net` already exists (`docker network create proxy_net`, usually already created by proxy-stack) before `docker compose up -d` — Compose merges the override automatically.
- **Not using it:** delete the override file, or run `docker compose -f docker-compose.yml up -d` explicitly, and reach Grafana via its direct host port instead.

### 4. Start the stack

```bash
docker compose up -d
```

Or using the bundled `Makefile` (auto-detects `docker-compose` vs `docker compose`):

```bash
make up      # docker compose up -d --build
make logs    # follow logs for all services
make clean   # docker compose down
make open    # opens http://localhost:3000/ (Grafana)
```

### 5. Verify the deployment

- **Grafana datasources:** `http://<host>:3000` (or your domain) → Connections → Data sources. Prometheus, Alertmanager, and Loki should all show green/working.
- **Prometheus targets:** `http://<host>:9090/targets` → confirm `prometheus`, `alertmanager`, the local `node-exporter`/`cadvisor`, and every edge-node target you configured are all `UP`.
- **Dashboards:** the three pre-provisioned dashboards (Node Metrics, Container Metrics, Log Search) should appear automatically in Grafana without manual import.

## Specific Notes

### Notification Channels

`docker-compose.yml` mounts `configs/alertmanager/alertmanager-fallback-config.yml` by default, which routes all alerts to the local `uncomplicated-alert-receiver` webhook viewer — no external credentials required. The receiver is exposed only on `127.0.0.1:${ALERT_RECEIVER_PORT:-9094}` and is **not** attached to `proxy_net`; open it through an SSH tunnel or add a reverse-proxy host if you want remote access. The fallback route groups for 30 s, re-groups every 5 min, and repeats an ongoing alert every 4 h.

Ready-to-edit templates for external channels live in the same directory:

- `alertmanager-telegram-config.yml` — native Telegram bot (recommended for a homelab: no public endpoint or SMTP server needed).
- `alertmanager-email-config.yml` — generic SMTP/email (works with any provider that offers SMTP and app passwords).
- `alertmanager-slack-config.yml` — Slack incoming webhook (legacy example).
- `alertmanager-opsgenie-config.yml` — Opsgenie API.
- `alertmanager-pushover-config.yml` — Pushover push notifications.

Telegram notifications use the HTML template in
`configs/alertmanager/templates/telegram.tmpl` (severity icon, instance, device,
container, summary, description and age). Edit that file to customize the
message, then restart Alertmanager.

To activate one:

1. Copy the chosen template to a private location, for example
   `~/alertmanager-telegram.local.yml` or a directory outside the repository.
2. Fill in the credentials. A `*.local.yml` file inside this directory is
   already ignored by Git.
3. Set `ALERTMANAGER_CONFIG_FILE` in `.env` (or in the Komodo stack
   environment) to the absolute path of that private file.
4. Recreate Alertmanager with `docker compose up -d --force-recreate alertmanager`.
5. Send a test alert:

   ```bash
   curl -XPOST http://127.0.0.1:9093/api/v2/alerts \
     -H 'Content-Type: application/json' \
     -d '[{"labels":{"alertname":"TestAlert","severity":"warning"},"annotations":{"summary":"Test notification"}}]'
   ```

Telegram: create a bot with `@BotFather`, copy its token, and get the chat ID
from `https://api.telegram.org/bot<TOKEN>/getUpdates` after sending the bot a
message. Email: use your provider's SMTP host/port and an app-specific
password; the template enables STARTTLS.

The active config file is `/etc/alertmanager/config.yml`, mounted from the file
selected by `ALERTMANAGER_CONFIG_FILE`. The `alertmanager.yml` shipped inside
the image is not used. Full alert labels remain available in the Alertmanager
UI and the UAR; notification messages are kept concise.

### Telegram Query Bot (Optional)

Alertmanager's Telegram integration only **sends** messages. For on-demand
queries, the stack includes a small read-only bot in `bot/telegram-bot.py`:

- `/alerts` — active alerts grouped by node, with severity, device and container.
- `/silences` — active silences and their matchers.
- `/status` — Alertmanager version, uptime and cluster state.
- `/help`, `/id` — command list and current chat ID.

The bot uses inline buttons (`Alerts`, `Silences`, `Status`, `Refresh`) and long
polling, so it needs no inbound port or public domain. It reads the bot token
and default chat ID from the same `ALERTMANAGER_CONFIG_FILE` used by
Alertmanager, so there is no second secret to manage. `TELEGRAM_ALLOWED_CHAT_IDS`
can add extra comma-separated chats; it defaults to the configured chat ID.

Alerts carry a `node` label (`primary` for the local targets, the configured
name for each remote target). The bot groups by that label. To show friendly
host names, set `NODE_DISPLAY_NAMES` in the stack environment:

```env
NODE_DISPLAY_NAMES=primary:primary-node,edge-node:edge-node-1
```

Enable it with the `telegram-bot` profile:

```env
COMPOSE_PROFILES=telegram-bot
```

Then recreate the stack (or just the new service). The service is disabled by
default. It is read-only: it can list alerts and silences but cannot create or
delete silences. Only one process should call Telegram `getUpdates` for a bot
token; stop manual `getUpdates` calls while the bot is running.

The container memory/CPU rules evaluate every container that has a cgroup limit, not just this monitoring stack. Containers without a CPU or memory limit are skipped by those rules because a percentage of “unlimited” is meaningless. Filesystem rules cover the host filesystems reported by node-exporter. `NodeDown` alerts when Prometheus cannot scrape a node-exporter target for more than 2 minutes, so an unreachable node is reported as well.

### Scraping Remote Nodes

New [monitoring-agent-gpnc](../monitoring-agent-gpnc/README.md) nodes are **not** auto-discovered. Prometheus reads remote targets from local files:

- `configs/prometheus/targets/node-exporter.yml`
- `configs/prometheus/targets/cadvisor.yml`

Copy the matching `*.yml.example` file, add one target group per edge node, and reload/restart Prometheus. The real files are ignored by Git because they normally contain private hostnames or IPs. Use an address reachable from the Prometheus container (for example a VPN/tailnet address) and set a stable `node` label for each node. Local targets use `node: primary`.

```yaml
- targets: [ '<edge-node>:9100' ]
  labels:
    container: node-exporter
    instance: '<edge-node-name>'
    node: '<edge-node-name>'
```
