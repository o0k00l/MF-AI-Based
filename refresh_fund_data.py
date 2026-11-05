"""Command-line entry point for engine-managed public fund data."""
from __future__ import annotations

import argparse
import json

from services.engine_fund_data import (
    EngineRuntimeConfig,
    load_engine_manifest,
    refresh_engine_fund_data,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("refresh", "status"))
    args = parser.parse_args(argv)
    config = EngineRuntimeConfig.from_environment()
    if args.command == "refresh":
        paths = refresh_engine_fund_data(config)
        manifest = load_engine_manifest(config.data_dir)
        print(json.dumps({
            "status": manifest["status"],
            "dataset_id": manifest["dataset_id"],
            "promotion_eligible": manifest["promotion_eligible"],
            "manifest": str(paths["manifest"]),
        }, indent=2))
        return 0
    print(json.dumps(load_engine_manifest(config.data_dir), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
