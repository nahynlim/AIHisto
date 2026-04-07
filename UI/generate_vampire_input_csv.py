"""Utilities for generating VAMPIRE-compatible dataset CSV files."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Iterable, Sequence

import pandas as pd


def clean_path(path_value: str) -> str:
    """Strip surrounding quotes and whitespace from a path-like string."""
    return str(path_value).strip().strip("'").strip('"')


def create_vampire_input_csv(
    folders: Sequence[str],
    conditions: Sequence[str],
    output_path: str,
    *,
    tag: str = "Segmented",
    mode: str = "apply",
    note: str = "",
) -> str:
    """Create a VAMPIRE dataset CSV for build/apply workflows."""
    folders = [clean_path(folder) for folder in folders]
    conditions = [str(condition).strip() for condition in conditions]
    output_path = clean_path(output_path)

    if not folders:
        raise ValueError("At least one folder is required.")
    if len(folders) != len(conditions):
        raise ValueError(
            f"Number of folders ({len(folders)}) and conditions ({len(conditions)}) must match."
        )
    if mode not in {"build", "apply"}:
        raise ValueError("Mode must be 'build' or 'apply'.")

    id_col = "setID" if mode == "build" else "set ID"
    rows = []
    for idx, (folder, condition) in enumerate(zip(folders, conditions), start=1):
        rows.append(
            {
                id_col: idx,
                "condition": condition,
                "set location": folder,
                "tag": tag,
                "note": note,
            }
        )

    df = pd.DataFrame(rows)[[id_col, "condition", "set location", "tag", "note"]]
    output_file = Path(output_path)
    output_file.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(output_file, index=False)
    return str(output_file)


def _prompt_for_folders() -> tuple[list[str], list[str]]:
    folders: list[str] = []
    conditions: list[str] = []
    print("Enter folders one by one. Press Enter with empty input when done.")
    index = 1
    while True:
        folder = clean_path(input(f"  Folder {index} path (or Enter to finish): "))
        if not folder:
            break
        condition = input(f"  Condition label for folder {index}: ").strip()
        folders.append(folder)
        conditions.append(condition)
        index += 1
    return folders, conditions


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate a VAMPIRE-compatible dataset CSV.")
    parser.add_argument("--folders", nargs="+", help="Paths to segmented image folders")
    parser.add_argument("--conditions", nargs="+", help="Condition label per folder")
    parser.add_argument("--output", help="Path to save the VAMPIRE input CSV")
    parser.add_argument("--tag", default="Segmented", help="Tag matching segmented image filenames")
    parser.add_argument("--mode", choices=["build", "apply"], default="apply")
    parser.add_argument("--note", default="", help="Optional note to include in the CSV")
    args = parser.parse_args(list(argv) if argv is not None else None)

    if not args.folders:
        folders, conditions = _prompt_for_folders()
        args.folders = folders
        args.conditions = conditions

    if not args.output:
        args.output = clean_path(input("Output CSV path: "))

    if args.conditions is None:
        raise ValueError("Conditions are required when folders are provided.")

    csv_path = create_vampire_input_csv(
        args.folders,
        args.conditions,
        args.output,
        tag=args.tag,
        mode=args.mode,
        note=args.note,
    )
    print(f"Done! {len(args.folders)} image set(s).")
    print(pd.read_csv(csv_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
