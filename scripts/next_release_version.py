#!/usr/bin/env python3
import glob
import re
import subprocess
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DIST_DIR = BASE_DIR / 'dist'
TAG_RE = re.compile(r'^v(\d+)\.(\d+)$')
PKG_RE = re.compile(r'^releaseplan-update-v(\d+)\.(\d+)\.tar\.gz$')

versions = []

try:
    raw = subprocess.check_output(['git', 'tag', '--list', 'v*'], cwd=BASE_DIR, text=True)
    for line in raw.splitlines():
        m = TAG_RE.fullmatch(line.strip())
        if m:
            versions.append((int(m.group(1)), int(m.group(2))))
except Exception:
    pass

for path in glob.glob(str(DIST_DIR / 'releaseplan-update-v*.tar.gz')):
    name = Path(path).name
    m = PKG_RE.fullmatch(name)
    if m:
        versions.append((int(m.group(1)), int(m.group(2))))

if versions:
    versions.sort()
    major, minor = versions[-1]
    print(f'{major}.{minor + 1}')
else:
    print('1.0')
