# Contributing to SMWC Downloader & Patcher

Thank you for helping improve SMWC Downloader & Patcher. This repository uses a manifest-driven build system and a native four-platform Candidate CI pipeline. Changes should preserve those contracts rather than introducing independent version, package, or platform logic.

## Development setup

Supported Python versions are defined by `product_manifest.json`. The current development line supports Python 3.11 through 3.13, and CI uses the exact Python version declared in `.github/workflows/smart-cicd.yml`.

### Windows PowerShell

```powershell
py -3.13 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-build.txt -r requirements-quality.txt
```

### macOS or Linux

```bash
python3.13 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt -r requirements-build.txt -r requirements-quality.txt
```

Linux development and frozen smoke tests also require Tk and a display server. Candidate CI installs `python3-tk` and uses `xvfb-run`.

## Authoritative project files

Use these files as the source of truth:

- `product_manifest.json`: product name, version, release channel, components, native targets, artifact names, resources, and hidden imports.
- `requirements.txt`: runtime dependencies.
- `requirements-build.txt`: build dependencies.
- `requirements-quality.txt`: quality and security tooling.
- `build_support/`: manifest validation, quality orchestration, native candidate packaging, smoke checks, and release evidence validation.

Do not introduce a second hard-coded product version in `main.py`, a PyInstaller spec, a workflow, or documentation. `version.txt` and `updater_version.txt` are generated metadata and must agree with the manifest.

## Branch and commit workflow

For v5.1 development, use a focused branch from the current integration line. Keep the upstream Save Data Sync reference branch unchanged so upstream behavior remains reviewable.

A focused change should:

1. Address one build, test, documentation, or product concern.
2. Add or update regression tests where behavior changes.
3. Avoid unrelated formatting or line-ending churn.
4. Pass the local source gate before it is pushed.
5. Pass Candidate CI on all four native targets before it is integrated.

Use clear imperative commit subjects, such as:

```text
build: add native candidate packaging
ci: build native candidates on pull requests
updater: disable in-place updates for development builds
docs: document the v5.1 build workflow
```

## Required validation

Run the source-only gate before every push:

```bash
python -m build_support.quality --skip-build
```

That command validates the manifest and generated metadata, runs all root `test_*.py` modules with coverage, byte-compiles the source tree, enforces the formatting contract, runs Ruff and mypy, and produces report-only security scans.

To view the exact stage plan without executing it:

```bash
python -m build_support.quality --skip-build --list-stages
```

To build, smoke-test, verify, and package the native target for the current machine:

```bash
python -m build_support.quality
```

Or invoke the candidate builder directly:

```bash
python -m build_support.build_candidate
```

A target can only be built on a matching host operating system and architecture. Cross-platform artifacts are produced by GitHub Actions, not by pretending a local host is another target.

## Tests and static scope

Root-level files named `test_*.py` are discovered automatically by the quality gate. New build-foundation tests should also be added to the explicit Ruff and formatting scopes in:

- `build_support/quality.py`
- `build_support/source_style.py`

Keep tests deterministic and offline. Mock network access, process execution, clocks, and filesystem replacement where practical.

## Manifest and packaging changes

When adding a runtime file or import required by a frozen executable:

1. Add the resource or hidden import under the correct component in `product_manifest.json`.
2. Add a validation or packaging regression test.
3. Run `python -m build_support.validate_manifest --json`.
4. Build the matching native candidate.
5. Confirm the frozen `--smoke-test` and verification report succeed.

Do not duplicate manifest data in platform-specific specs. The thin PyInstaller specs consume shared configuration from `build_support`.

## Candidate CI evidence

`.github/workflows/smart-cicd.yml` runs on supported development branches, pull requests, and manual dispatch. A successful run must contain:

- `source-quality-coverage`
- `windows-x86_64`
- `linux-x86_64`
- `macos-arm64`
- `macos-x86_64`

Each native artifact contains the package, SHA-256 sidecar, frozen smoke report, and verification report for the same source revision.

## Release safety

Development builds use the `development` release channel. They deliberately skip update checks and refuse in-place replacement. Install newer development candidates manually.

Do not create a stable tag from the current development manifest. Final publication is fail-closed and requires a separate release-preparation change, a stable manifest identity, and complete same-revision Candidate CI evidence. See `.github/BUILD_INSTRUCTIONS.md` and `VERSION_MANAGEMENT.md`.

## Pull-request review checklist

Before requesting review, confirm that:

- the diff is focused and contains no generated build output;
- product identity still comes only from `product_manifest.json`;
- source validation passes locally;
- Candidate CI is green on all four native targets;
- user-visible behavior or workflow changes are documented;
- development builds cannot publish or update themselves as stable releases.
