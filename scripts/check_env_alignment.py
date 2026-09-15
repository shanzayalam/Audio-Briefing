#!/usr/bin/env python3
"""
scripts/check_env_alignment.py

Verifies that .env and .env.example contain exactly the same set of keys.
Exits with code 1 (failing the CI step) if there are any mismatches.

Usage:
    python scripts/check_env_alignment.py                  # compares .env vs .env.example
    python scripts/check_env_alignment.py --ci             # CI mode: skips .env check
"""

import sys
import os
import argparse


def parse_env_keys(filepath: str) -> set:
    """Return the set of variable names defined in an env file."""
    keys = set()
    with open(filepath, encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key = line.split("=", 1)[0].strip()
                if key:
                    keys.add(key)
    return keys


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ci",
        action="store_true",
        help="CI mode: only check that .env.example exists; skip .env comparison.",
    )
    args = parser.parse_args()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    example_path = os.path.join(repo_root, ".env.example")
    env_path = os.path.join(repo_root, ".env")

    if not os.path.exists(example_path):
        print("FAIL  .env.example not found -- please create it.")
        sys.exit(1)

    example_keys = parse_env_keys(example_path)
    print(f"OK    .env.example found with {len(example_keys)} keys.")

    if args.ci:
        print("INFO  CI mode: skipping .env comparison (file not present in CI).")
        sys.exit(0)

    if not os.path.exists(env_path):
        print("WARN  .env not found -- skipping alignment check (first-time setup?).")
        sys.exit(0)

    env_keys = parse_env_keys(env_path)

    in_example_not_env = example_keys - env_keys
    in_env_not_example = env_keys - example_keys

    ok = True

    if in_example_not_env:
        ok = False
        print(
            f"\nFAIL  Keys in .env.example but MISSING from .env "
            f"({len(in_example_not_env)}):"
        )
        for k in sorted(in_example_not_env):
            print(f"        - {k}")

    if in_env_not_example:
        ok = False
        print(
            f"\nFAIL  Keys in .env but MISSING from .env.example "
            f"({len(in_env_not_example)}):"
        )
        for k in sorted(in_env_not_example):
            print(f"        - {k}")

    if ok:
        print(
            f"OK    .env and .env.example are fully aligned "
            f"({len(env_keys)} keys each)."
        )
        sys.exit(0)
    else:
        print(
            "\nFIX   Update .env.example to match .env (or vice-versa), "
            "then re-run this script."
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
