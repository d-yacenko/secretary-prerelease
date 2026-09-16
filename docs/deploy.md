# VDS deployment (phase 01)

Target path: `/opt/secretary`

## First deploy

```bash
mkdir -p /opt/secretary
cd /opt/secretary
git clone https://github.com/d-yacenko/secretary-prerelease.git .
cp .env.example .env
# VDS: bind API on localhost, avoid port clashes with other services
echo 'SECRETARY_API_BIND=127.0.0.1:18080' >> .env
cd infra
docker compose --env-file ../.env -f compose.yaml -f compose.deploy.yaml up -d --build
curl -s http://127.0.0.1:18080/health
```

## Local dev

```bash
cd infra
docker compose -f compose.yaml -f compose.dev.yaml up -d --build
curl -s http://localhost:8000/health
```

## Update (VDS)

```bash
cd /opt/secretary
git pull
cd infra
docker compose -f compose.yaml -f compose.deploy.yaml up -d --build
```

PostgreSQL is not published on the host in production. API listens on `127.0.0.1:18080` on the VDS.

HTTPS via nginx + Certbot on `<your-domain.example>` is a later step.
