# Import Python libraries
import os
import re
import shutil
import time
import uuid
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
# Bump when the processing changes so old bundles are ignored instead of read with the wrong shape
SCHEMA_VERSION = "v1"


def resolve_path(path):
    # Relative paths in config.toml start at the repo root, so the dashboard and preload script share one cache
    path = Path(path)
    return path if path.is_absolute() else REPO_ROOT / path


class CacheStore:
    """Processed dashboard data saved as parquet in one folder that every user (and the preload script) reads.

    A bundle is a folder of DataFrames written to a temporary folder and renamed into place, so a
    reader never sees a half written bundle while another process is saving it.
    """

    def __init__(self, cache_dir):
        self.root = resolve_path(cache_dir) / SCHEMA_VERSION
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def slug(name):
        return re.sub(r'[^a-z0-9]+', '_', str(name).lower()).strip('_')

    def bundle_dir(self, *keys):
        return self.root.joinpath(*(self.slug(key) for key in keys))

    def has_bundle(self, *keys):
        return self.bundle_dir(*keys).is_dir()

    def bundle_age_hours(self, *keys):
        path = self.bundle_dir(*keys)
        return (time.time() - path.stat().st_mtime) / 3600 if path.is_dir() else None

    def load_bundle(self, *keys):
        path = self.bundle_dir(*keys)
        if not path.is_dir():
            return None
        return {file.stem: pd.read_parquet(file) for file in path.glob('*.parquet')}

    def save_bundle(self, frames, *keys):
        path = self.bundle_dir(*keys)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        tmp_path.mkdir()
        for name, frame in frames.items():
            frame.to_parquet(tmp_path / f"{name}.parquet", index=False)
        # Rename the old bundle out of the way first, Windows cannot replace a folder that exists
        old_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.old")
        try:
            os.replace(path, old_path)
        except FileNotFoundError:
            pass
        try:
            os.replace(tmp_path, path)
        except OSError:
            # Another process saved the same bundle at the same moment, its copy is just as good
            shutil.rmtree(tmp_path, ignore_errors=True)
        shutil.rmtree(old_path, ignore_errors=True)
