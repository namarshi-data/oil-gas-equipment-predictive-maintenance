"""Azure ML v2 batch endpoint adapter; also executable in local smoke tests."""
from pathlib import Path
import os
import sys

import pandas as pd

# Azure ships the repository code snapshot, without installing this package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from energy_failure.batch_score import BatchScorer  # noqa: E402

_scorer: BatchScorer | None = None


def init() -> None:
    global _scorer
    model_root = Path(os.environ["AZUREML_MODEL_DIR"])
    candidates = list(model_root.rglob("model.joblib"))
    if len(candidates) != 1:
        raise ValueError("Registered model must contain exactly one model.joblib")
    _scorer = BatchScorer(candidates[0])


def run(mini_batch: list[str]) -> pd.DataFrame:
    if _scorer is None:
        raise RuntimeError("init() must load the model before scoring")
    if not mini_batch:
        raise ValueError("Batch cannot be empty")
    # Raising causes a failed batch, rather than silently dropping bad records.
    return pd.concat([_scorer.score_csv(path) for path in mini_batch], ignore_index=True)