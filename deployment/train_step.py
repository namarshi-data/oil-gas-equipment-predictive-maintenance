"""Azure ML component wrapper around the reproducible local experiment."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-output", type=Path, required=True)
    parser.add_argument("--model-output", type=Path, required=True)
    parser.add_argument("--features-output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    environment = os.environ.copy()
    environment["PYTHONPATH"] = str(root / "src")
    subprocess.run([sys.executable, "-m", "energy_failure.pipeline", "--output-root",
                    str(args.run_output.resolve())], cwd=root, env=environment, check=True)
    args.model_output.mkdir(parents=True, exist_ok=True)
    args.features_output.mkdir(parents=True, exist_ok=True)
    shutil.copy2(args.run_output / "artifacts" / "model.joblib", args.model_output / "model.joblib")
    for name in ("features.json", "metrics.json", "provenance.json"):
        source = args.run_output / "artifacts" / name
        if source.exists():
            shutil.copy2(source, args.model_output / name)
    shutil.copy2(args.run_output / "data" / "processed" / "batch_features.csv",
                 args.features_output / "batch_features.csv")


if __name__ == "__main__":
    main()