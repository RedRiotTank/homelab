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
[node-exporter]   [cadvisor]  ◄── over Tailscale (100.64.x.x) ─── monitoring-agent-gpnc on remote/edge nodes
 @100.64.0.2       @100.64.0.2
 (crimsonserver)   (crimsonserver)
```

### Shared `monitoring` network

All services here join a single external Docker network literally named `monitoring`. This is the same network every other stack's `docker-compose.override.yml` attaches to (as `monitoring_net`) in order to let Promtail discover their containers and ship logs here. This stack does not need its own override file — it *is* the hub the other stacks' overrides connect to.

### Pull metrics locally, pull metrics remotely, push logs everywhere

Metrics use a pull model: Prometheus scrapes `node-exporter` and `cadvisor` on the local host directly, and *also* scrapes the equivalent exporters running on remote/edge nodes via hardcoded `static_configs` targets reached over the Tailscale mesh (e.g. `100.64.0.2:9100`, `100.64.0.2:8080`, labeled `instance: crimsonserver`). See [monitoring-agent-gpnc](../monitoring-agent-gpnc/README.md) for the lightweight agent deployed on those remote nodes. Logs use the opposite model: Promtail instances (local, and the ones bundled into every other stack via their override layer) push log streams into Loki.

### Alerting defaults to a safe no-op channel

Alertmanager's active config (`configs/alertmanager/alertmanager-fallback-config.yml`) routes every alert to `uncomplicated-alert-receiver`, a simple webhook-based viewer, so the stack is usable out of the box without any third-party notification credentials. Four additional ready-to-use templates for real channels (Slack, Email, Opsgenie, Pushover) ship alongside it — see [Specific Notes](#specific-notes).

### Externally managed data volumes

Unlike every other stack in this repository (which declares its own named volumes), `grafana-data`, `prometheus-data`, and `loki-data` are declared `external: true`, parameterized via `GRAFANA_DATA_VOLUME`, `PROMETHEUS_DATA_VOLUME`, and `LOKI_DATA_VOLUME` (defaulting to `monitoring-stack-gpnc_grafana-data`, etc.). Docker Compose will **not** create these automatically — they must already exist (from a prior deployment) or be created manually before the first `up`. This is a deliberate guard against accidentally recreating/losing the stack's historical metrics and dashboards state when the compose project is redeployed or renamed. See [Deployment & Operational Commands](#deployment--operational-commands).

### Consistent labeling via YAML anchors

The compose file defines `x-logging` and `x-common-labels` anchors applied to every service, guaranteeing uniform JSON-file log rotation (`max-size: 1m`, `max-file: 1`) and consistent Promtail-discovery labels (`logging: promtail`, `logging_jobname: monitoring`, `stackname: docker-monitoring-stack-gpnc`) without repeating configuration per service.

## Service Interconnections & Dependencies

This is the stack every other service ships telemetry to. Services that attach to the shared `monitoring`/`monitoring_net` Docker network via their own `docker-compose.override.yml`:

- [adguard](../adguard/README.md) — ships container logs via Promtail labels.
- [backrest](../backrest/README.md) — ships container logs via Promtail labels.
- [headscale](../headscale/README.md) — ships container logs via Promtail labels.
- [proxy-stack](../proxy-stack/README.md) — ships container logs via Promtail labels.
- [tailscale-client](../tailscale-client/README.md) — labels only (runs in `network_mode: host`, so it cannot join `monitoring_net`; labels are still read by the local Promtail instance on that host).
- [komodo](../komodo/README.md) — optionally joins both `proxy_net` and `monitoring_net` via its own host-managed override example.
- [monitoring-agent-gpnc](../monitoring-agent-gpnc/README.md) — remote/edge-node counterpart; its `node-exporter`/`cadvisor` are scraped by this stack's Prometheus over Tailscale, and its Promtail pushes logs directly to this stack's Loki via `LOKI_URL`.

## File Structure

```text
monitoring-stack-gpnc/
├── docker-compose.yml        # grafana, prometheus, cadvisor, node-exporter,
│                              # alertmanager, uncomplicated-alert-receiver, redis, loki, promtail
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
| `MONITORING_MEM_LIMIT` | `512m` | Per-service memory limit (applied uniformly). |
| `TIMEZONE` | `Europe/Madrid` | Reference timezone for the stack (informational). |
| `GRAFANA_PORT` / `PROMETHEUS_PORT` / `ALERTMANAGER_PORT` / `ALERT_RECEIVER_PORT` / `REDIS_PORT` / `LOKI_PORT` | unset (exposed on all interfaces by default) | Optional — set to `127.0.0.1:<port>` to restrict to localhost when running behind [proxy-stack](../proxy-stack/README.md). |
| `GRAFANA_DATA_VOLUME` / `PROMETHEUS_DATA_VOLUME` / `LOKI_DATA_VOLUME` | `monitoring-stack-gpnc_grafana-data` / `..._prometheus-data` / `..._loki-data` | Names of the pre-existing **external** volumes (see prerequisite below). |
| `HOST_STACKS_PATH` / `CONTAINER_STACKS_PATH` | `/opt` | Host path where compose projects live (informational/portability). |

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

### 3. Start the stack

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

### 4. Verify the deployment

- **Grafana datasources:** `http://<host>:3000` (or your domain) → Connections → Data sources. Prometheus, Alertmanager, and Loki should all show green/working.
- **Prometheus targets:** `http://<host>:9090/targets` → confirm `prometheus`, `alertmanager`, `node-exporter` (local + `crimsonserver`), and `cadvisor` (local + `crimsonserver`) are all `UP`.
- **Dashboards:** the three pre-provisioned dashboards (Node Metrics, Container Metrics, Log Search) should appear automatically in Grafana without manual import.

## Specific Notes

### Alerting Channel Templates

`docker-compose.yml` mounts `configs/alertmanager/alertmanager-fallback-config.yml` by default, which routes all alerts to the local `uncomplicated-alert-receiver` webhook viewer — no external credentials required. Four alternative, ready-to-edit templates exist in the same directory for real notification channels, each with severity-based routing already configured:

- `alertmanager-slack-config.yml` — Slack incoming webhook.
- `alertmanager-email-config.yml` — SMTP/email (e.g. SendGrid).
- `alertmanager-opsgenie-config.yml` — Opsgenie API.
- `alertmanager-pushover-config.yml` — Pushover push notifications.

To activate one: fill in its placeholder credentials (API keys, webhook URLs, tokens), then update the `alertmanager` service's volume mount in `docker-compose.yml` to point at the chosen file instead of the fallback, and restart the `alertmanager` container.

### Scraping Remote Nodes

New [monitoring-agent-gpnc](../monitoring-agent-gpnc/README.md) nodes are **not** auto-discovered — Prometheus uses static targets. To register a new remote node, add entries to `configs/prometheus/prometheus.yml` under the `node-exporter` and `cadvisor` jobs, following the existing pattern:

```yaml
  - job_name: node-exporter
    static_configs:
      - targets: [ 'node-exporter:9100' ]
        labels: { container: 'node-exporter', instance: 'redserver' }
      - targets: [ '<new-node-tailscale-ip>:9100' ]
        labels: { container: 'node-exporter', instance: '<new-node-name>' }
```

Reach the node over its Tailscale IP (not its LAN IP), matching how `crimsonserver` is reached at `100.64.0.2`. Reload Prometheus (`docker compose restart prometheus` or a `SIGHUP`/reload-endpoint call) after editing.
