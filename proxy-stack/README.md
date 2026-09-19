# Proxy Stack (Nginx Proxy Manager + Cloudflare DDNS)

Edge routing and dynamic DNS infrastructure for the homelab. This stack manages public reverse proxying, Let's Encrypt SSL/TLS certificates, and automated Cloudflare DNS synchronization.

## Features

- **Nginx Proxy Manager (NPM):** Web GUI for reverse proxy configuration, access lists, and SSL lifecycle management.
- **Localhost Admin Binding:** Protects port `81` by binding it exclusively to `127.0.0.1`.
- **Cloudflare DDNS:** Periodically updates zone A records against WAN IP changes.
- **Monitoring Integration:** Ready for Promtail/Loki log ingestion via `docker-compose.override.yml`.

## Prerequisites

1. Create the shared external network if it does not exist:

    ```bash
   docker network create proxy_net
    ```
2.  A Cloudflare API Token with `Zone - DNS - Edit` permissions.
    
## Setup & Deployment

1.  Copy and populate environment variables:
    
    ```Bash    
    cp .env.example .env
    nano .env
    ```   
    
2.  (Optional) Inject monitoring network via override:
    
    ```Bash
    # docker-compose.override.yml maps logs into Promtail
    ```    
    
3.  Start the stack:
    
    ```Bash
    docker compose up -d
    ```   
    

## Default Credentials (NPM First Boot)

-   **Email:** `admin@example.com`
    
-   **Password:** `changeme` _(You will be prompted to update these upon initial login)._
