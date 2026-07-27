"""Render the native candidate matrix consumed by GitHub Actions."""
from __future__ import annotations

import json
from typing import Any

from build_support.manifest import SUPPORTED_TARGETS, target_config


def candidate_matrix() -> dict[str, list[dict[str, Any]]]:
    """Return a deterministic GitHub Actions include matrix.

    The product manifest remains the authority for runner, platform,
    architecture, and artifact naming.  Keeping the workflow free of a second
    hand-maintained target list prevents CI and local packaging from drifting.
    """

    include: list[dict[str, Any]] = []
    for target_name in SUPPORTED_TARGETS:
        target = target_config(target_name)
        include.append(
            {
                "target": target_name,
                "runner": target["runner"],
                "platform": target["platform"],
                "architecture": target["architecture"],
                "artifact_name": target["artifact_name"],
            }
        )
    return {"include": include}


def render_matrix() -> str:
    """Return compact stable JSON suitable for ``$GITHUB_OUTPUT``."""

    return json.dumps(candidate_matrix(), separators=(",", ":"), sort_keys=True)


def main() -> int:
    print(render_matrix())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
