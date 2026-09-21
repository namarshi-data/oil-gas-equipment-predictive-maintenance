"""Content-based model identity and a portable training provenance manifest."""
from __future__ import annotations
import hashlib
import importlib.metadata
import json
from pathlib import Path
import platform
import subprocess


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_provenance(repo: Path, raw: Path, config: dict, features: list[str], algorithm: str, threshold: float) -> dict:
    code = {p.relative_to(repo).as_posix(): file_hash(p) for folder, suffix in (("src", "*.py"), ("sql", "*.sql"))
            for p in sorted((repo/folder).rglob(suffix))}
    data = {p.name: file_hash(p) for p in sorted(raw.glob("*.csv"))}
    env_files = {str(p.relative_to(repo).as_posix()): file_hash(p) for name in ("deployment/conda.yml", "deployment/environment.yml", "pyproject.toml")
                 if (p := repo/name).exists()}
    runtime = {"python": platform.python_version(), **{name: importlib.metadata.version(name)
               for name in ("numpy", "pandas", "scikit-learn", "scipy", "joblib")}}
    commit = None
    try:
        top = subprocess.check_output(["git", "rev-parse", "--show-toplevel"], cwd=repo, stderr=subprocess.DEVNULL, text=True).strip()
        if Path(top).resolve() == repo.resolve():
            commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, stderr=subprocess.DEVNULL, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        pass
    payload = {"contract_version": 3, "code_sha256": digest(code), "data_sha256": digest(data),
               "config_sha256": digest(config), "feature_schema_sha256": digest(features),
               "environment_sha256": digest({"files": env_files, "runtime": runtime}),
               "algorithm": algorithm, "threshold": float(threshold)}
    model_version = "energy-v3-" + digest(payload)[:20]
    return {**payload, "model_version": model_version, "git_commit": commit, "code_files": code,
            "data_files": data, "environment_files": env_files, "runtime": runtime,
            "config": config, "features": features}
