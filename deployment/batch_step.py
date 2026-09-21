"""Pipeline smoke component using the exact endpoint scorer."""
from pathlib import Path
import argparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from energy_failure.batch_score import BatchScorer  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    predictions = BatchScorer(args.model / "model.joblib").score_csv(args.features / "batch_features.csv")
    args.output.mkdir(parents=True, exist_ok=True)
    predictions.to_csv(args.output / "predictions.csv", index=False)
    print(f"Validated {len(predictions)} scoring rows")


if __name__ == "__main__":
    main()