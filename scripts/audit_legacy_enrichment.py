"""Create the full preserved-HTML inventory without DB access or network requests."""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "src"))

from klegal_gold.enrichment.corpus_inventory import run_inventory  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--processes", type=int, choices=range(1, 5), default=1)
    args = parser.parse_args()
    last = 0

    def progress(status: dict[str, int]) -> None:
        nonlocal last
        if status["rows"] - last >= 1024 or status["rows"] == status["expected_rows"]:
            print(json.dumps(status), flush=True)
            last = status["rows"]

    result = run_inventory(
        args.parquet, args.output_dir, progress=progress, processes=args.processes
    )
    print(
        json.dumps(
            {
                "output_dir": str(args.output_dir.resolve()),
                "totals": result["totals"],
                "error_codes": result["error_codes"],
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
