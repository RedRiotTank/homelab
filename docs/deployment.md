# Deployment

This repository is a collection of Docker Compose stacks. It does **not** assume
a specific hostname, domain, IP address, directory layout, cloud provider, or
orchestrator. The examples use placeholders and can be adapted to a single host
or a multi-node environment.

## Repository layout

Each stack lives in its own directory:

```text
core/<stack>/      # infrastructure stacks
compose/<stack>/   # application stacks
```

A stack directory contains:

- `docker-compose.yml` — the portable base definition.
- `docker-compose.override.yml` — optional host-specific network and logging
  concerns.
- `.env.example` — a template for the variables the stack consumes.
- `README.md` — stack-specific setup and operational notes.

The repository itself can be cloned anywhere. Keep persistent data outside the
repository.

## Configuration

Copy the example environment file and adjust it for your host:

```bash
cp .env.example .env
$EDITOR .env
docker compose up -d
```

Compose automatically loads `.env` from the project directory. The file is
ignored by Git; never commit real credentials.

Values in `.env.example` are templates. In particular:

- Domains and URLs use `example.com` or `<your-domain>`.
- Host paths use `/path/to/...` or a documented default such as `/opt/...`.
- Passwords, tokens, and keys are placeholders.
- Optional integrations are disabled or left empty.

## Overrides

The base compose file should stay portable. Put host-specific concerns in
`docker-compose.override.yml`:

- Attaching a service to an external network such as `proxy_net` or `monitoring`.
- Adding logging labels.
- Binding ports to a loopback address.
- Mounting a certificate or host-specific configuration file.

If you do not use a shared monitoring stack, remove the `monitoring_net` entries
and logging labels from the override instead of deleting the whole file.

## Resource limits

Every service in this repository defines a CPU limit and a memory limit. They are
**baseline caps, not reservations**: they protect the host from a runaway
container without preventing services from using spare capacity. Adjust them in
the stack's compose file for your hardware.

The defaults are intentionally conservative:

- Light services: `0.25–0.5` CPU and `128–512 MiB`.
- Medium applications and databases: `1–2` CPU and `1–2 GiB`.
- Jellyfin is deliberately higher (`6` CPU / `10 GiB`) because it is the primary
  media workload and indexing/transcoding can be heavy.

The Telegram bot's `/containers` command shows each container's live CPU and
memory against its limit. A warning marker appears if a limit is missing.

## Deployment models

### Single host

Deploy the stacks you need with Docker Compose. Create shared external networks
first:

```bash
docker network create proxy_net
```

Then deploy the owning stacks (for example the reverse proxy and monitoring
stack) before the applications that attach to those networks.

### Orchestrator

Any orchestrator that can run Docker Compose or equivalent definitions can be
used. Point it at the stack directory, provide the environment values through
its secret/environment mechanism, and let it manage the lifecycle.

### Multi-node

A typical split is:

- **Primary node:** full infrastructure stack, including the reverse proxy,
  DNS/VPN control plane, monitoring hub, orchestration, and backups.
- **Edge node(s):** lightweight agents such as the VPN client, the orchestration
  agent, and the monitoring agent.

Connect nodes over a private network (VPN, WireGuard, Tailscale/Headscale, or a
private LAN). Remote scrape targets and node names are deployment data; keep them
in local, uncommitted files.

## Persistent data and backups

Choose a data-root layout that fits your host, for example:

```text
<data-root>/<stack>/       # application or service state
<config-root>/<stack>/     # configuration that must not live in Git
```

Configure those paths through `.env`. Back them up with your preferred tool.
`core/backrest/` is an optional example based on Restic, but it is not required.

## Monitoring

The central monitoring stack and the per-node agent are optional. If you use
them:

- Keep the central Prometheus/Loki data in persistent volumes or host paths.
- Put remote target definitions in local, uncommitted files (by default
  `core/monitoring-stack-gpnc/configs/prometheus/targets/*.yml`; set
  `PROMETHEUS_TARGETS_DIR` to use a directory outside the repository).
- Push logs from other stacks by adding the logging labels shown in their
  overrides; network membership alone is not required.

## Security checklist

- Do not commit `.env`, keys, certificates, tokens, or real infrastructure data.
- Bind management interfaces to loopback or a private network.
- Use a reverse proxy for TLS termination.
- Restrict orchestrator and monitoring endpoints to trusted networks.
- Review the `.env.example` of each stack before deploying it.
