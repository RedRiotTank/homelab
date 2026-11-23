# Homelab Stacks

A collection of self-hosted Docker Compose stacks, split into two layers:

- **`core/`** — infrastructure services: DNS, VPN, ingress, orchestration,
  observability, backups, and secrets.
- **`compose/`** — applications: media, books, dashboards, game servers, and
  other user-facing services.

Each stack is self-contained and follows the same shape:

```text
<stack>/
├── docker-compose.yml           # portable base definition
├── docker-compose.override.yml  # optional host-specific networks/labels
├── .env.example                 # configuration template
└── README.md                    # setup, operation, and verification
```

## Quick start

```bash
cd core/proxy-stack          # or any other stack
cp .env.example .env
$EDITOR .env                 # set paths, domains, ports, credentials
docker compose up -d
```

Some stacks depend on shared external Docker networks such as `proxy_net` and
`monitoring`. Create them first or deploy the stack that owns them.

## Configuration

- Real `.env` files are ignored by Git. Only `.env.example` files are committed.
- Examples use placeholders such as `example.com`, `<your-host>`,
  `<your-domain>`, and `/path/to/...`. Replace them with values for your
  environment.
- Never commit secrets, private keys, real hostnames, internal IPs, or
  environment-specific configuration.
- Overrides belong in `docker-compose.override.yml` when they are host-specific;
  keep the base compose file portable.

## Deployment options

The repository does not require a specific orchestrator. You can deploy a stack
with:

- Docker Compose directly on a host.
- Any GitOps or container-management platform (for example Komodo, Portainer, or
  a systemd unit).
- A multi-node setup: deploy the full `core/` stack on a primary node and the
  lightweight agents on edge nodes.

See [`docs/deployment.md`](docs/deployment.md) for a generic deployment model.

## Persistent data

Persistent state should live outside the repository, either in named Docker
volumes or in host directories that you configure through `.env`. Back up those
paths separately; `core/backrest/` is an optional example of how to do that.

## Monitoring

[`core/monitoring-stack-gpnc/`](core/monitoring-stack-gpnc/) is an optional
central Grafana/Prometheus/Loki/Alertmanager stack.
[`core/monitoring-agent-gpnc/`](core/monitoring-agent-gpnc/) is the optional
per-node agent for edge nodes. Remote scrape targets are supplied locally and are
not committed to this repository.

## License

Each stack keeps the license of its upstream project where applicable. See the
individual stack directories for details.
