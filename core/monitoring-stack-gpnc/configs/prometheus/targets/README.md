# Prometheus remote targets

The central Prometheus scrapes its own local exporters directly. Remote nodes
are supplied through `file_sd_configs` from local files mounted at
`/etc/prometheus/targets`:

- `node-exporter.yml`
- `cadvisor.yml`

Only the `*.yml.example` files are committed. Copy each one to its real name
(`node-exporter.yml.example` → `node-exporter.yml`,
`cadvisor.yml.example` → `cadvisor.yml`) and fill in the targets for your edge
nodes. The real files are ignored by Git because they normally contain private
hostnames or IP addresses.

By default the directory is `./configs/prometheus/targets`. To keep private
targets outside the repository (and outside a Git checkout), set
`PROMETHEUS_TARGETS_DIR` in `.env` to another host directory and mount it with
the same files.

Example:

```yaml
- targets: [ '<edge-node>:9100' ]
  labels:
    container: node-exporter
    instance: '<edge-node-name>'
```

Use the address that is reachable from the Prometheus container, for example a
private LAN address or a VPN/tailnet address. Reload or restart Prometheus after
changing the files.
