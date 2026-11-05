"""Write reports/eval.md and reports/eval.json."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from switchboard.evaluation import evaluate, write_reports


def main() -> None:
    summary = evaluate()
    path = write_reports(summary)
    misses = summary["misses"]
    print(f"gold {summary['gold_accuracy'] * 100:.1f}%  savings {summary['savings_pct']}%  -> {path}")
    if misses:
        for miss in misses:
            print(
                f"MISS {miss['id']}: expected {miss['expected_outcome']}/{miss['expected_model']} "
                f"got {miss['outcome']}/{miss['chosen_model']}"
            )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
