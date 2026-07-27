# Build and Release Instructions

SMWC Downloader & Patcher uses one manifest-backed build path locally and in GitHub Actions. The same native builder creates the application, updater, smoke report, verification report, checksum, and final package for each supported target.

## Supported native targets

The authoritative target list and artifact names are in `product_manifest.json`:

| Target | GitHub runner | Package type |
| --- | --- | --- |
| `windows-x86_64` | `windows-latest` | ZIP |
| `linux-x86_64` | `ubuntu-24.04` | `tar.gz` |
| `macos-arm64` | `macos-15` | DMG |
| `macos-x86_64` | `macos-15-intel` | DMG |

There is no Universal macOS package and no AppImage target in the current build contract. Intel and Apple Silicon macOS candidates are built and verified separately.

## Dependency layers

Install all three constrained requirement files for development and packaging:

```bash
python -m pip install \
  -r requirements.txt \
  -r requirements-build.txt \
  -r requirements-quality.txt
```

- `requirements.txt`: application runtime.
- `requirements-build.txt`: PyInstaller and packaging support.
- `requirements-quality.txt`: coverage, Ruff, mypy, Bandit, pip-audit, and detect-secrets.

The supported Python range comes from `product_manifest.json`. GitHub Actions uses the exact Python patch version declared in the workflow environment.

## Validate without building

Run the complete source gate:

```bash
python -m build_support.quality --skip-build
```

List the deterministic stage plan:

```bash
python -m build_support.quality --skip-build --list-stages
```

The source gate includes manifest/generated-metadata validation, all root `test_*.py` modules with branch coverage, byte-compilation, formatting checks, Ruff, mypy, and report-only security scans.

On Linux, run GUI-dependent tests through a virtual display:

```bash
xvfb-run -a python -m build_support.quality --skip-build
```

## Build one native candidate locally

Build the target matching the current host:

```bash
python -m build_support.quality
```

The lower-level equivalent is:

```bash
python -m build_support.build_candidate
```

An explicit target may be selected:

```bash
python -m build_support.build_candidate --target windows-x86_64
```

The command rejects a target that does not match the current platform and architecture. Native packages must be built on their actual target platform.

Successful output is written under `artifacts/` and includes:

```text
<manifest artifact name>
<manifest artifact name>.sha256
<target>-smoke.json
<target>-verification.json
```

The frozen application is launched in non-GUI `--smoke-test` mode before packaging. Verification checks product identity, source revision, target platform, architecture, package contents, executable metadata where supported, and package digest.

## Candidate CI

Workflow: `.github/workflows/smart-cicd.yml`

Display name: **v5.1 Candidate CI**

It runs on:

- pushes to `main`, `develop`, `feature/**`, and `integration/**`;
- pull requests;
- manual dispatch.

### Source-quality job

The source job runs on Ubuntu and:

1. derives the native matrix from `product_manifest.json`;
2. installs constrained dependencies;
3. runs `python -m build_support.quality --skip-build` under Xvfb;
4. uploads the hidden `.coverage` database as `source-quality-coverage`.

### Native matrix jobs

After source quality succeeds, independent jobs build:

- `windows-x86_64`
- `linux-x86_64`
- `macos-arm64`
- `macos-x86_64`

Each job runs the tests relevant to the native phase, builds the application and updater, executes the frozen smoke test, verifies the package, and uploads its evidence. Matrix jobs do not depend on artifacts produced by another operating system.

## Inspecting a Candidate CI run

From the GitHub Actions run page:

1. Confirm **Source quality and tests** is green.
2. Confirm all four **Build `<target>`** jobs are green.
3. Confirm the Artifacts section contains the coverage artifact and all four target artifacts.
4. Download the package for the platform being manually checked.
5. For Windows, extract into an empty directory and launch `SMWC Downloader.exe`.

Development candidates are unsigned. Operating-system reputation or Gatekeeper warnings are therefore possible and are separate from build verification.

## Final release gate

Workflow: `.github/workflows/final-release.yml`

Display name: **Final Release**

The workflow does not build replacement artifacts. It locates a successful Candidate CI **push** run from the same repository and exact tagged revision, downloads all native evidence, and runs:

```bash
python -m build_support.release_gate \
  --artifacts-dir artifacts \
  --expected-revision <git-sha> \
  --expected-tag v5.1.0 \
  --output release-manifest.json
```

Publication is refused unless:

- the tag uses stable `vMAJOR.MINOR.PATCH` form;
- tag and manifest versions agree;
- the manifest is in a stable/release channel;
- the successful Candidate CI run is for the same clean revision;
- all four manifest targets are present exactly once;
- packages are non-empty;
- SHA-256 sidecars match;
- smoke and verification reports are successful and mutually consistent;
- no GitHub release already exists for the tag.

The published release contains the four packages, four checksums, four smoke reports, four verification reports, and consolidated `release-manifest.json`.

## Current development restriction

The current manifest is `5.1.0-dev.1` in the `development` channel. It is intentionally not publishable as a stable release, and the updater is intentionally disabled.

A future release-preparation commit must update and validate all stable-version assumptions before a stable tag is created. Do not edit only a tag or one generated metadata file.

## Troubleshooting

### Local import failure

Install the constrained runtime requirements with the same interpreter used by validation:

```bash
python -m pip install -r requirements.txt
```

### Git warns about LF/CRLF

Windows may report that LF files will be checked out as CRLF. This is normally informational. Avoid unrelated line-ending-only commits.

### Frozen import or resource failure

Add the dependency to the appropriate manifest-backed hidden-import or resource list, add a regression test, and rerun the native candidate build. Do not patch only one platform spec.

### macOS packaging warning

Treat PyInstaller deprecation warnings as follow-up build work even when the current candidate succeeds. Do not silently suppress them without correcting the underlying packaging contract.
