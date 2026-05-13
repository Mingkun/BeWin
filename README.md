# ReleasePlan

ReleasePlan project repository.

## Structure

- `docs/` documentation
- `src/` source code
- `scripts/` helper scripts
- `tests/` tests

## Portable deployment package

This project now supports a portable deployment package for another server.

### Build package

```bash
chmod +x package_release.sh
./package_release.sh
```

Output:

- `dist/releaseplan-portable.tar.gz`

## Docker deployment (recommended for old systems)

If the target server has an old Python version, use Docker.

### Prerequisites

- Docker installed
- Optional: Docker Compose installed

### Option A: single-command Docker run

Without proxy:

```bash
tar -xf releaseplan-portable.tar.gz
cd releaseplan-portable
chmod +x run-docker.sh
./run-docker.sh
```

With proxy:

```bash
tar -xf releaseplan-portable.tar.gz
cd releaseplan-portable
chmod +x run-docker.sh
export PROXY_URL='http://username:password@proxy-host:proxy-port'
./run-docker.sh
```

Dockerfile also includes proxy placeholders, so you can build directly with:

```bash
docker build \
  --build-arg http_proxy='http://username:password@proxy-host:proxy-port' \
  --build-arg https_proxy='http://username:password@proxy-host:proxy-port' \
  -t releaseplan:latest .
```

Then visit:

- `http://<server-ip>:5010/`

### Option B: docker compose

```bash
tar -xf releaseplan-portable.tar.gz
cd releaseplan-portable
docker compose up -d --build
```

### Docker notes

- Container uses Python 3.11 internally
- Host `./data` is mounted to `/app/data`
- Host `./docs` is mounted to `/app/docs`
- Default published port: `5010`
- Dockerfile defaults to common China mirrors for apt and pip, to reduce overseas download failures
- If `PROXY_URL` is set, it is passed to both `docker build` and `docker run`

### Common Docker commands

```bash
docker ps
docker logs -f releaseplan
docker restart releaseplan
docker stop releaseplan
docker rm -f releaseplan
```

## Native systemd deployment

If the target server Python version is new enough, you can still use the native installer.

```bash
tar -xf releaseplan-portable.tar.gz
cd releaseplan-portable
chmod +x install.sh
sudo ./install.sh
```

This installer will:

- create `.venv`
- install dependencies
- generate `start.sh`
- install and enable `releaseplan.service`
- start or restart the service automatically

### Service management

```bash
systemctl status releaseplan.service
systemctl restart releaseplan.service
journalctl -u releaseplan.service -f
```

To uninstall the service:

```bash
./uninstall.sh
```

### Environment variables

Copy/edit `.env` as needed:

- `RELEASEPLAN_SECRET_KEY`
- `RELEASEPLAN_OAUTH_ENABLED`
- `RELEASEPLAN_OAUTH_AUTHORIZE_URL`
- `RELEASEPLAN_OAUTH_TOKEN_URL`
- `RELEASEPLAN_OAUTH_USERINFO_URL`
- `RELEASEPLAN_OAUTH_CLIENT_ID`
- `RELEASEPLAN_OAUTH_CLIENT_SECRET`
- `RELEASEPLAN_OAUTH_SCOPE`
- `RELEASEPLAN_OAUTH_REDIRECT_URI`
- `RELEASEPLAN_OAUTH_LOGOUT_URL`
- `HOST`
- `PORT`

By default it runs on `0.0.0.0:5010`.
