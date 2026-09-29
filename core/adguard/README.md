# AdGuard Home Stack

Network-wide ad-blocking, privacy-preserving DNS server, and the core routing brain for the homelab's Split-Brain DNS architecture. 

## Architecture & Traffic Flow

To ensure maximum portability and prevent file permission issues, this stack uses **native Docker volumes** for its database (`adguard_work`) and configuration file (`adguard_conf`).

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

## Security & DNS Routing (The SNAT Workaround)

To achieve a true **Split-Brain DNS** without exposing our proxy to the public internet, clients need different IP resolutions for our domain (`*.example.com`).

Because AdGuard runs inside the `proxy_net` Docker network, UDP DNS queries coming from [Headscale](https://www.google.com/search?q=../headscale/README.md) VPN clients (`100.64.x.x`) are Source-NAT'd (SNAT) by the Docker gateway. AdGuard sees these requests as coming from the Docker network gateway (e.g., `172.20.0.1`) rather than the actual Tailscale IP.

**The Solution:** DO NOT use the standard "DNS Rewrites" tab, as it overrides everything globally. Instead, use **Custom Filtering Rules** in the AdGuard UI (`Filters -> Custom filtering rules`) to exploit the SNAT behavior:

    ! 1. If the client is Docker/Tailscale SNAT (172.20.0.1), return the VPN tunnel IP
    ||yourdomain.com^$client=172.20.0.1,dnsrewrite=100.64.0.1
    
    ! 2. For everyone else (e.g., physical LAN clients), return the physical host IP
    ||yourdomain.com^$client=~172.20.0.1,dnsrewrite=192.168.1.182
    

_(Note: Replace `yourdomain.com` and the IPs with your actual environment values. If the Split-DNS breaks in the future after a Docker network recreation, check the AdGuard Query Log to see if the `172.20.0.1` gateway IP has shifted to a different subnet)._

## Prerequisites

### 1\. Disable `systemd-resolved` Port 53 Listener (Host Machine)

By default, Ubuntu/Debian systemd binds to port 53. If port 53 conflicts, free it up before deploying:

    sudo sed -r -i.orig 's/#?DNSStubListener=yes/DNSStubListener=no/g' /etc/systemd/resolved.conf
    sudo systemctl restart systemd-resolved
    

### 2\. External Networks

Create the shared external ingress network if it does not exist (typically managed by the [Proxy Stack](https://www.google.com/search?q=../proxy-stack/README.md)):

    docker network create proxy_net
    

## Observability & The Override Layer

This repository includes a `docker-compose.override.yml` file designed to integrate this stack with the homelab's central observability infrastructure (Promtail/Loki) via the `monitoring_net`.

For more details on the telemetry network, see the [Monitoring Stack Documentation](https://www.google.com/search?q=../monitoring-stack-gpnc/README.md).

**⚠️ Optional Feature:** The override is completely optional. If you do not have the monitoring stack deployed:

-   **Komodo Users:** Simply omit `docker-compose.override.yml` from the "File Paths" configuration.
    
-   **CLI Users:** Delete the override file, or explicitly run `docker compose -f docker-compose.yml up -d`.
    

## Setup & Deployment

### Option A: GitOps via Komodo (Recommended)

1.  Add this repository to your Komodo instance.
    
2.  Set the environment variables in the Komodo UI based on the `.env.example` structure.
    
3.  In "File Paths", list both `docker-compose.yml` and `docker-compose.override.yml` (if using monitoring).
    
4.  Click Deploy.
    

### Option B: Manual CLI Deployment

1.  Copy and populate the environment variables:
    
        cp .env.example .env
        nano .env
        
    
2.  Start the stack:
    
        docker compose up -d
        
    

## Post-Deployment Access

-   **Initial Setup Wizard:** Access via local SSH tunnel on port `3030` (`http://localhost:3030`).
    
-   **Main Dashboard:** Access securely via [Nginx Proxy Manager](https://www.google.com/search?q=../proxy-stack/README.md) using the container name `adguardhome` on port `80`, or locally via port `8053`. Both interfaces are bound to `127.0.0.1` on the host to prevent unauthorized LAN access.
