#!/usr/bin/env python3
import argparse
import csv
import re
from collections import Counter
from pathlib import Path


DEFAULT_INPUT = Path(
    "/Users/ayobamidele/Documents/postgres_full_database_log_export/"
    "postgres_evaluation_details.csv"
)


def safe_filename(value):
    value = str(value or "blank").strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return value.strip("._") or "blank"


def split_by_use_case(input_path, output_dir):
    input_path = Path(input_path).expanduser().resolve()
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    writers = {}
    files = {}
    counts = Counter()

    try:
        with input_path.open(newline="", encoding="utf-8-sig") as source:
            reader = csv.DictReader(source)

            if not reader.fieldnames:
                raise ValueError(f"No CSV header found in {input_path}")

            if "use_case" not in reader.fieldnames:
                raise ValueError("CSV must contain a 'use_case' column")

            for row in reader:
                use_case = row.get("use_case") or "blank"
                counts[use_case] += 1

                if use_case not in writers:
                    output_path = output_dir / (
                        f"{safe_filename(use_case)}_evaluation_details.csv"
                    )
                    handle = output_path.open(
                        "w",
                        newline="",
                        encoding="utf-8"
                    )
                    writer = csv.DictWriter(handle, fieldnames=reader.fieldnames)
                    writer.writeheader()
                    files[use_case] = handle
                    writers[use_case] = writer

                writers[use_case].writerow(row)
    finally:
        for handle in files.values():
            handle.close()

    return counts, output_dir


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Split postgres_evaluation_details.csv into one all-column CSV "
            "per use case."
        )
    )
    parser.add_argument(
        "input_csv",
        nargs="?",
        default=DEFAULT_INPUT,
        help=f"Input evaluation details CSV. Default: {DEFAULT_INPUT}"
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default="use_case_evaluation_details",
        help="Directory for per-use-case CSV files."
    )
    args = parser.parse_args()

    counts, output_dir = split_by_use_case(args.input_csv, args.output_dir)

    print(f"Wrote {len(counts)} use-case files to {output_dir}")
    for use_case, count in sorted(counts.items()):
        print(f"{use_case}: {count} rows")


if __name__ == "__main__":
    main()
