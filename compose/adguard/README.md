# AdGuard Home Stack

Network-wide ad-blocking and privacy-preserving DNS server deployment.

## Features

- **DNS Sinkhole:** Blocks network-wide advertisements, tracking domains, and malware.
- **Localhost Admin Binding:** Protects administrative interfaces (`3000` setup wizard and `80` main dashboard) by binding them to `127.0.0.1`.
- **Dual-Network Override:** Integrates natively with `proxy_net` for domain routing and `monitoring` for Promtail log ingestion.

## Prerequisites

### 1. Disable `systemd-resolved` Port 53 Listener (Host Machine)
By default, Ubuntu/Debian systemd binds to port 53. If port 53 conflicts:
```bash
sudo sed -r -i.orig 's/#?DNSStubListener=yes/DNSStubListener=no/g' /etc/systemd/resolved.conf
sudo systemctl restart systemd-resolved
```

### 2\. External Networks

Ensure the shared networks exist if using the compose override:

```Bash
docker network create proxy_net
```    

## Setup & Deployment

1.  Copy and adjust the environment template:
    
    ```Bash
    cp .env.example .env
    nano .env
    ```    
    
2.  Start the container:
    
    ```Bash
    docker compose up -d
    ```    
    
3.  Complete initial setup via reverse proxy or SSH tunnel to port `3030`, then manage the dashboard on port `8053`.
