# Monitoring Agent (GPNC)

A lightweight, per-node telemetry agent (cAdvisor + Node Exporter + Promtail) deployed on secondary/edge nodes (e.g. `crimsonserver`) to feed the central [monitoring-stack-gpnc](../monitoring-stack-gpnc/README.md) running on the primary node. It carries no dashboards, no storage, and no alerting of its own — it exists purely to expose metrics endpoints and push log streams back to the hub.

## Architecture & Design Decisions

```text
┌─────────────────────── Secondary/Edge Node (e.g. crimsonserver) ───────────────────────┐
│                                                                                          │
│   [ cadvisor-${NODE_HOSTNAME} ]  :8080  ──┐                                             │
│   [ node-exporter-${NODE_HOSTNAME} ] :9100 ─┤  exposed on host ports, no 127.0.0.1 bind │
│                                             │                                           │
│   [ promtail-${NODE_HOSTNAME} ] ───────────┼──── pushes logs (LOKI_URL) ────────┐       │
└─────────────────────────────────────────────┼───────────────────────────────────┼───────┘
                                               │ scraped (pull)                    │ pushed
                                               ▼ over Tailscale mesh (100.64.x.x)  ▼
                              ┌──────────────────────────────────────────────────────┐
                              │        monitoring-stack-gpnc (primary node)          │
                              │   Prometheus  ◄── scrapes  │  Loki  ◄── receives     │
                              └──────────────────────────────────────────────────────┘
```

### Two telemetry models, by design

- **Metrics: pull, over the VPN mesh.** `cadvisor` (`:8080`) and `node-exporter` (`:9100`) are published directly on the host's ports — not bound to `127.0.0.1` — because the central Prometheus on the primary node must be able to scrape them remotely. `prometheus.yml` in [monitoring-stack-gpnc](../monitoring-stack-gpnc/README.md) targets this node at its Tailscale IP (e.g. `100.64.0.2:9100`, `100.64.0.2:8080`, labeled `instance: crimsonserver`), not its LAN IP. This means the node running this agent **must** already be joined to the tailnet via [tailscale-client](../tailscale-client/README.md) before the central stack can see it — the ports are intentionally open on all interfaces because the exposure is meant to be reached over the private mesh, not the public internet. If this host also has a public-facing NIC, firewall these ports to the Tailscale interface (see [Specific Notes](#specific-notes)).
- **Logs: push, to the central Loki.** `promtail` here is configured with `LOKI_URL` pointing at the central Loki's Tailscale address (e.g. `http://100.x.x.x:3100/loki/api/v1/push`) and actively ships logs outward. This is the opposite flow from metrics — there is no remote log *pull*.

### Per-node naming and labeling

Container names (`cadvisor-${NODE_HOSTNAME}`, `node-exporter-${NODE_HOSTNAME}`, `promtail-${NODE_HOSTNAME}`) and the `NODE_HOSTNAME` environment variable disambiguate this node's telemetry from every other node's when multiple secondary nodes report into the same central stack. `configs/promtail-client.yaml` relabels scraped Docker logs to set the `job` label from each container's `logging_jobname` label and the `host` label from `NODE_HOSTNAME`, mirroring the labeling convention used by the central Promtail in [monitoring-stack-gpnc](../monitoring-stack-gpnc/README.md) so logs from every node are queryable consistently in Grafana.

### `privileged: true` and `pid: host`

cAdvisor needs both to introspect host-level cgroups, namespaces, and process trees for accurate per-container resource metrics — this is the same requirement as the central stack's cAdvisor, just scoped to this single node.

### Image choice: `zcube/cadvisor` vs `gcr.io/cadvisor/cadvisor`

This agent uses `zcube/cadvisor:latest`, a community-maintained fork with broader kernel/architecture compatibility (useful on edge hardware that may run newer or non-standard kernels), instead of the upstream `gcr.io/cadvisor/cadvisor` image used by [monitoring-stack-gpnc](../monitoring-stack-gpnc/README.md). The two are functionally equivalent for this agent's purposes.

### Conservative resource limits

`AGENT_CPUS` and `AGENT_MEM_LIMIT` default to `0.5` CPU / `256m` per service — tighter than the central stack's `0.5` CPU / `512m` defaults — since this agent runs alongside real workloads on an edge node rather than on dedicated monitoring hardware.

### No override file

Unlike most other stacks in this repo, there is no `docker-compose.override.yml` here. Every other override exists to attach a service to a shared external Docker network (`proxy_net`, `monitoring_net`); this agent has nothing to attach to — its entire integration model is flat host-port exposure (for scraping) and an outbound HTTP push (for logs), not a shared Docker network.

## Service Interconnections & Dependencies

- [monitoring-stack-gpnc](../monitoring-stack-gpnc/README.md) — the hard dependency: this agent's `cadvisor`/`node-exporter` are scraped by its Prometheus, and its `promtail` pushes logs to its Loki via `LOKI_URL`.
- [tailscale-client](../tailscale-client/README.md) — required on the same node so a routable `100.64.x.x` tailnet IP exists for the central stack to reach this agent's exposed ports.
- [komodo-periphery](../komodo-periphery/README.md) — typically co-located on the same secondary node for remote stack management.

## File Structure

| File | Purpose |
| --- | --- |
| `docker-compose.yml` | Defines `cadvisor`, `node-exporter`, and `promtail` services — no override file, no named volumes beyond what the images require internally. |
| `.env.example` | Template for required environment variables (hostname, Loki URL, image versions, ports, resource limits). |
| `configs/promtail-client.yaml` | Promtail scrape/relabel config: Docker service discovery, `job` label from `logging_jobname`, `host` label from `NODE_HOSTNAME`. |

## Configuration & Environment Variables

| Variable | Default | Purpose |
| --- | --- | --- |
| `NODE_HOSTNAME` | `agent` | Identifies this node in container names and in the `host`/`instance` labels seen centrally in Grafana/Prometheus. |
| `LOKI_URL` | _(required)_ | Push endpoint for the central Loki, reached over the Tailscale mesh (e.g. `http://100.x.x.x:3100/loki/api/v1/push`). |
| `CADVISOR_VERSION` | `v0.46.0` | `zcube/cadvisor` image tag. |
| `NODE_EXPORTER_VERSION` | `v1.5.0` | `prom/node-exporter` image tag. |
| `PROMTAIL_VERSION` | `3.5.0` | `grafana/promtail` image tag. |
| `CADVISOR_PORT` | `8080` | Host port cAdvisor is scraped on. |
| `NODE_EXPORTER_PORT` | `9100` | Host port Node Exporter is scraped on. |
| `AGENT_CPUS` | `0.5` | Per-service CPU limit (applied uniformly). |
| `AGENT_MEM_LIMIT` | `256m` | Per-service memory limit (applied uniformly). |

## Deployment & Operational Commands

```bash
cp .env.example .env
nano .env   # set NODE_HOSTNAME and LOKI_URL at minimum
docker compose up -d
```

### Verify the deployment

- On the central [monitoring-stack-gpnc](../monitoring-stack-gpnc/README.md) host, open Prometheus targets (`http://<host>:9090/targets`) and confirm `node-exporter` and `cadvisor` show this node's `instance` label as `UP`. If not yet registered, see that stack's [Scraping Remote Nodes](../monitoring-stack-gpnc/README.md#specific-notes) note for adding a new static target.
- In Grafana's Log Search dashboard (or Loki Explore), filter by `host="${NODE_HOSTNAME}"` and confirm recent log lines are arriving.

## Specific Notes

`CADVISOR_PORT` and `NODE_EXPORTER_PORT` are published on all host interfaces by default (no `127.0.0.1` binding), since the whole point is to let the central Prometheus scrape them remotely over the Tailscale mesh. If this host also has a public-facing or untrusted LAN interface, restrict exposure at the host firewall level (e.g. `ufw`/`iptables`) to only accept connections on these ports from the Tailscale interface or the primary node's tailnet IP.
