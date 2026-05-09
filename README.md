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

Then start:

```bash
./start.sh
```

### Environment variables

Copy/edit `.env` as needed:

- `RELEASEPLAN_SECRET_KEY`
- `RELEASEPLAN_SAML_ENABLED`
- `RELEASEPLAN_SAML_SETTINGS`
- `HOST`
- `PORT`

By default it runs on `0.0.0.0:5010`.
