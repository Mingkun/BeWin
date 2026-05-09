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

### Install on target server

```bash
tar -xzf releaseplan-portable.tar.gz
cd releaseplan-portable
chmod +x install.sh
./install.sh
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
- `RELEASEPLAN_SAML_ENABLED`
- `RELEASEPLAN_SAML_SETTINGS`
- `HOST`
- `PORT`

By default it runs on `0.0.0.0:5010`.
