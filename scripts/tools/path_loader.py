#!/usr/bin/env python3
"""
Path configuration loader.
Provides machine-aware path resolution for all A-LEMS scripts and ETL.

All functions follow the 3-layer resolution pattern:
    Layer 1: ALEMS_DATA_ROOT env var + hostname  (GN100, remote machines)
    Layer 2: app_settings.yaml / config file      (UBUNTU2505 default)
    Layer 3: hardcoded project fallback           (safe default)

Sources ~/.alemsrc internally (Ab Initio pattern) — self-contained.
No caller needs to pre-source the rc file.
"""

import os
import socket
import yaml
from pathlib import Path


def _source_alemsrc():
    # type: () -> None
    """
    Source ~/.alemsrc if present. Sets ALEMS_DATA_ROOT and API keys.
    Uses setdefault so shell environment always wins over rc file.
    Called automatically by get_alems_db_path() and get_baseline_cache_path().
    """
    alemsrc = os.path.expanduser("~/.alemsrc")
    if not os.path.exists(alemsrc):
        return
    with open(alemsrc) as f:
        for line in f:
            line = line.strip()
            if not line.startswith("export "):
                continue                     # skip comments and blank lines
            key, _, val = line[7:].partition("=")
            os.environ.setdefault(key.strip(), val.strip())


def get_alems_db_path():
    # type: () -> str
    """
    Resolve the correct SQLite DB path for this machine.

    Priority:
      Layer 1: ALEMS_DATA_ROOT env var + hostname
               -> $ALEMS_DATA_ROOT/$hostname/experiments.db
      Layer 2: app_settings.yaml database.sqlite.path (relative)
      Layer 3: hardcoded fallback -> data/experiments.db

    Returns:
        Path string for experiments.db on this machine.
    """
    _source_alemsrc()
    base = os.environ.get("ALEMS_DATA_ROOT")
    if base:
        machine_id = socket.gethostname().lower()
        return f"{base}/{machine_id}/experiments.db"
    return "data/experiments.db"


def get_baseline_cache_path():
    # type: () -> str
    """
    Resolve idle_baseline.json cache path for this machine.

    Same 3-layer logic as get_alems_db_path() — cache lives alongside DB.

    Priority:
      Layer 1: ALEMS_DATA_ROOT env var + hostname
               -> $ALEMS_DATA_ROOT/$hostname/idle_baseline.json
      Layer 2: app_settings.yaml experiment.baseline.cache_file
      Layer 3: hardcoded fallback -> data/idle_baseline.json

    Returns:
        Path string for idle_baseline.json on this machine.
    """
    _source_alemsrc()
    base = os.environ.get("ALEMS_DATA_ROOT")
    if base:
        # Layer 1: machine-specific directory alongside experiments.db
        machine_id = socket.gethostname().lower()
        return os.path.join(base, machine_id, "idle_baseline.json")

    # Layer 2: read from app_settings.yaml
    project_root = Path(__file__).parent.parent.parent
    try:
        settings_path = project_root / "config" / "app_settings.yaml"
        if settings_path.exists():
            with open(settings_path) as f:
                settings = yaml.safe_load(f) or {}
            cache_file = (settings
                          .get("experiment", {})
                          .get("baseline", {})
                          .get("cache_file", ""))
            if cache_file:
                return str(project_root / cache_file)
    except Exception:
        pass   # yaml not available or parse error — fall through to Layer 3

    # Layer 3: hardcoded fallback
    return str(project_root / "data" / "idle_baseline.json")


class PathConfig:
    def __init__(self, config_file=None):
        if config_file is None:
            self.config_file = Path(__file__).parent.parent.parent / "config" / "paths.yaml"
        else:
            self.config_file = Path(config_file)

        self.load()
        self.load_db_path()

    def load(self):
        with open(self.config_file) as f:
            self.config = yaml.safe_load(f)

        project_root = Path(__file__).parent.parent.parent

        project = self.config.get('project', {})
        self.PROJECT_NAME = project.get('name', 'A-LEMS')
        self.REPO_URL     = project.get('repo_url', '')
        self.AUTHOR       = project.get('author', '')
        self.DESCRIPTION  = project.get('description', '')

        docs = self.config['docs']
        self.GUIDES_PATH  = project_root / docs['guides']

        generated = docs['generated']
        self.API_OUTPUT    = project_root / generated['api']
        self.SPHINX_OUTPUT = project_root / generated['sphinx']
        self.MKDOCS_OUTPUT = project_root / generated['mkdocs']

        self.ASSETS_PATH      = project_root / docs['assets']
        self.DIAGRAMS_OUTPUT  = project_root / docs['diagrams']
        self.MKDOCS_DIAGRAMS  = project_root / docs['mkdocs_diagrams']

        sources = self.config['sources']
        self.SPHINX_SOURCE = project_root / sources['sphinx']['source']
        self.SPHINX_CONFIG = project_root / sources['sphinx']['config']
        self.MKDOCS_SOURCE = project_root / sources['mkdocs']['source']
        self.MKDOCS_CONFIG = project_root / sources['mkdocs']['config']

        tools = self.config['tools']
        self.TOOL_DIAGRAMS = project_root / tools['diagrams']
        self.TOOL_REPORTS  = project_root / tools['reports']

        for path in [self.GUIDES_PATH, self.API_OUTPUT,
                     self.SPHINX_OUTPUT, self.MKDOCS_OUTPUT,
                     self.ASSETS_PATH, self.DIAGRAMS_OUTPUT,
                     self.SPHINX_SOURCE, self.MKDOCS_SOURCE,
                     self.TOOL_DIAGRAMS, self.TOOL_REPORTS]:
            path.mkdir(parents=True, exist_ok=True)

    def load_db_path(self):
        """Load database path using machine-aware resolution."""
        # Use the same resolution logic as get_alems_db_path()
        self.DB_PATH = Path(get_alems_db_path())

    def __str__(self):
        return (
            f"PathConfig:\n"
            f"  Project: {self.PROJECT_NAME}\n"
            f"  Author:  {self.AUTHOR}\n"
            f"  Repo:    {self.REPO_URL}\n"
            f"  MkDocs:  {self.MKDOCS_SOURCE}\n"
            f"  DB:      {getattr(self, 'DB_PATH', 'Not configured')}"
        )


# Global instance for legacy callers
config = PathConfig()

if __name__ == "__main__":
    print(config)
    print(f"\nDB path:        {get_alems_db_path()}")
    print(f"Baseline cache: {get_baseline_cache_path()}")
