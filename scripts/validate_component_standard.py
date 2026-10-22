#!/usr/bin/env python3
"""Validate the repository against its AdvFab component declaration."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "charts/re8ch-advanced-fabric/Chart.yaml"
VALUES = ROOT / "charts/re8ch-advanced-fabric/values.yaml"


def fail(message: str) -> None:
    raise ValueError(message)


def chart_versions() -> tuple[str, str]:
    text = CHART.read_text()
    version = re.search(r"^version:\s*([^\s]+)\s*$", text, re.MULTILINE)
    app_version = re.search(r'^appVersion:\s*["\']?([^\s"\']+)', text, re.MULTILINE)
    if not version or not app_version:
        fail("chart must declare version and appVersion")
    return version.group(1), app_version.group(1)


def validate(requested_version: str | None = None) -> dict[str, object]:
    declaration = json.loads((ROOT / "component-standard.json").read_text())
    if declaration.get("schemaVersion") != "advfab.org/component-standard/v1":
        fail("unsupported component standard schema")

    chart_version, app_version = chart_versions()
    if chart_version != app_version:
        fail(f"chart version {chart_version!r} differs from appVersion {app_version!r}")
    if requested_version and requested_version.removeprefix("v") != chart_version:
        fail(f"release version {requested_version!r} differs from {chart_version!r}")

    referenced_paths: list[str] = []
    referenced_paths.extend(item["path"] for item in declaration["contracts"])
    referenced_paths.extend(declaration["assurance"]["securityAutomation"])
    referenced_paths.extend(declaration["assurance"]["requiredDocumentation"])
    referenced_paths.append(declaration["release"]["workflow"])
    for artifact in declaration["release"]["artifacts"]:
        referenced_paths.append(artifact["source"])
        if "{version}" not in artifact["reference"]:
            fail(f"{artifact['id']}: release reference must contain {{version}}")
    missing = sorted(path for path in set(referenced_paths) if not (ROOT / path).is_file())
    if missing:
        fail(f"declared repository paths do not exist: {missing}")

    values = VALUES.read_text()
    for key in ("enabled: false", "applyEnabled: false"):
        if key not in values:
            fail(f"safe default is missing from values.yaml: {key}")
    image_values = re.findall(r'^[ \t]*image:[ \t]*["\']?([^\s"\']+)', values, re.MULTILINE)
    mutable_images = [image for image in image_values if ":" in image and "@sha256:" not in image]
    if mutable_images:
        fail(f"runtime image references must include a digest: {mutable_images}")

    workflow = (ROOT / declaration["release"]["workflow"]).read_text()
    for marker in ("cosign sign", "attest-build-provenance", "spdx", "sha256"):
        if marker not in workflow:
            fail(f"release workflow lacks required evidence marker: {marker}")

    return {
        "component": declaration["component"]["name"],
        "version": chart_version,
        "contracts": len(declaration["contracts"]),
        "artifacts": [item["id"] for item in declaration["release"]["artifacts"]],
        "status": "valid",
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--release-version")
    args = parser.parse_args()
    try:
        print(json.dumps(validate(args.release_version), indent=2))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"component standard validation failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
