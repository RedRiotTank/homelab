# Proxy Stack (Nginx Proxy Manager + Cloudflare DDNS)

Edge routing and dynamic DNS infrastructure for the homelab. This stack manages public reverse proxying, Let's Encrypt SSL/TLS certificates, and automated Cloudflare DNS synchronization.

## Architecture & Traffic Flow

To ensure maximum portability and prevent file permission issues, this stack uses **native Docker volumes** instead of host bind mounts for its database (`npm_data`) and certificates (`npm_letsencrypt`).

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

## Security & DNS Routing (Best Practices)

Exposing services directly to the public internet is risky. For private homelab services (like Proxmox, Komodo, or internal dashboards), it is highly recommended to implement a **Split DNS** architecture using AdGuard Home and NPM Access Lists.

### 1\. AdGuard Home (Split DNS)

Instead of internal traffic going out to the public internet and bouncing back (Hairpin NAT), configure AdGuard to resolve your domains locally:

-   Go to your [AdGuard Home](https://www.google.com/search?q=../adguard/README.md) dashboard.
    
-   Navigate to **Filters -> DNS Rewrites**.
    
-   Add a rewrite for your domain (e.g., `*.example.com`) pointing directly to the **private internal IP** of the server hosting this proxy stack (e.g., `192.168.1.X`).
    
-   _Result:_ When you are on your local network or connected via Tailscale, traffic flows directly to the server, never touching the public internet.
    

### 2\. NPM Access Lists (Whitelisting)

To block public access to your private services, use Nginx Proxy Manager's **Access Lists**:

-   In NPM, go to **Access Lists** and create one named "Private Local & VPN Only".
    
-   Under the **Access** tab, set `allow` rules for your private subnets (e.g., `192.168.1.0/24` for LAN, `100.64.0.0/10` for Tailscale).
    
-   Apply this Access List to your private proxy hosts.
    
-   _Result:_ If someone tries to access your service from a public IP, NPM will block them with a `403 Forbidden` error, but you will still access it seamlessly and securely with a valid SSL certificate.
    

## Prerequisites

1.  Create the shared external ingress network if it does not exist:
    
    Bash
    
        docker network create proxy_net
        
    
2.  A Cloudflare API Token with `Zone - DNS - Edit` permissions.
    

## Observability & The Override Layer

This repository includes a `docker-compose.override.yml` file designed to integrate this stack with the homelab's central observability infrastructure (Promtail/Loki).

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
        
    

## Default Credentials (NPM First Boot)

If this is a fresh installation with an empty `npm_data` volume, use the default credentials to access the admin portal on port `81`:

-   **Email:** `admin@example.com`
    
-   **Password:** `changeme` _(You will be forced to update these upon initial login)._
