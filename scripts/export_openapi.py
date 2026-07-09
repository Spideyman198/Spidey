"""Export the OpenAPI spec to docs/api/openapi.json (or verify freshness).

Usage:
    python scripts/export_openapi.py <output-path>          # write
    python scripts/export_openapi.py --check <output-path>  # CI freshness gate

App construction needs valid settings but never touches the network, so
placeholder local DSNs are injected when the environment doesn't provide real
ones. Output is deterministically serialized (sorted keys) so a git diff is a
meaningful freshness check.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

_EXPORT_ENV_DEFAULTS = {
    "SPIDEY_ENVIRONMENT": "test",
    "SPIDEY_DATABASE_URL": "postgresql+asyncpg://export:export@localhost:5432/export",
    "SPIDEY_REDIS_URL": "redis://localhost:6379/0",
    "SPIDEY_QDRANT_URL": "http://localhost:6333",
}


def _render_spec() -> str:
    for key, value in _EXPORT_ENV_DEFAULTS.items():
        os.environ.setdefault(key, value)

    from spidey.api.main import create_app  # imported after env is ready
    from spidey.platform.config import Settings

    app = create_app(Settings())
    return json.dumps(app.openapi(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("output", type=Path)
    parser.add_argument("--check", action="store_true", help="fail if the file is stale")
    args = parser.parse_args(argv)

    spec = _render_spec()

    if args.check:
        if not args.output.is_file():
            print(f"missing committed spec: {args.output}", file=sys.stderr)
            return 1
        if args.output.read_text(encoding="utf-8") != spec:
            print(
                f"{args.output} is stale — regenerate with: python scripts/export_openapi.py {args.output}",
                file=sys.stderr,
            )
            return 1
        print("openapi spec is fresh")
        return 0

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(spec, encoding="utf-8")
    print(f"wrote {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
