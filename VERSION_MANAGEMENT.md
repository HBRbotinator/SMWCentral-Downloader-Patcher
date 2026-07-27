# Product Identity and Version Management

## Authoritative source

`product_manifest.json` is the single source of truth for SMWC Downloader & Patcher identity and packaging. It owns:

- product ID and display name;
- development or release version;
- PEP 440 version;
- release channel;
- publisher and copyright;
- supported Python range;
- Windows and macOS numeric metadata;
- application and updater identities;
- supported native targets and artifact names;
- PyInstaller resources, package data, and hidden imports.

Do not add an independent version constant to `main.py`, workflows, PyInstaller specs, or release scripts.

## Runtime identity

`product_identity.py` validates the manifest and exports runtime constants such as:

```python
PRODUCT_DISPLAY_NAME
PRODUCT_VERSION
PEP440_VERSION
RELEASE_CHANNEL
VERSION
WINDOWS_VERSION_TUPLE
MACOS_SHORT_VERSION
MACOS_BUNDLE_VERSION
```

Both source execution and frozen execution load the same manifest. The manifest is included in the application and updater packages as a required runtime resource.

## Generated package metadata

`package_metadata.py` and `build_support.metadata` derive platform metadata from the manifest.

Generated files include:

- `version.txt` for the Windows application;
- `updater_version.txt` for the Windows updater;
- macOS bundle display, short, and bundle versions;
- `build_identity.json` inside candidate output;
- smoke and verification reports;
- target-specific package filenames and checksums.

Generated metadata must not be treated as an editable source of truth.

## Current development version

The current line uses:

```text
Product version: 5.1.0-dev.1
PEP 440 version: 5.1.0.dev1
Release channel: development
Display version: v5.1.0-dev.1
```

The development suffix is represented consistently in Windows numeric and macOS bundle metadata. `python -m build_support.validate_manifest --json` checks these relationships.

## Updating a development version

Change the related manifest fields together:

1. `product.version`
2. `product.pep440_version`
3. `versions.windows_numeric`
4. `versions.macos_short`
5. `versions.macos_bundle`
6. every `targets.<target>.artifact_name`

The updater component's `product_id` and `release_channel` must continue matching the product section.

Then run:

```bash
python -m build_support.validate_manifest --json
python -m unittest -v test_product_identity.py test_package_metadata.py test_build_configuration.py
python -m build_support.quality --skip-build
```

Do not manually edit only `version.txt`, `updater_version.txt`, or a README filename.

## Release channels and updater policy

`update_policy.py` resolves update behavior from the manifest release channel.

- `development`: update discovery and in-place replacement are disabled.
- `stable` or `release`: updater support is enabled.
- empty or unknown channels: fail closed.

This prevents a development candidate from replacing itself with an older stable build or invoking the standalone replacement helper.

## Stable release preparation

The current validation model is deliberately development-first. A stable release requires a focused release-preparation change rather than editing only the tag.

That change must, at minimum:

1. define and validate the stable version representation;
2. set the manifest release channel to `stable` or `release`;
3. update all native artifact names;
4. regenerate and verify Windows/macOS metadata;
5. confirm updater policy is enabled only for the intended stable build;
6. pass source validation and all four native Candidate CI jobs;
7. create a clean `vMAJOR.MINOR.PATCH` tag on that exact successful revision.

The Final Release workflow then verifies all same-revision candidate evidence and creates `release-manifest.json`. It refuses duplicate, incomplete, dirty, mixed-revision, development-channel, or checksum-invalid releases.

## Useful commands

Validate identity and generated metadata:

```bash
python -m build_support.validate_manifest --json
```

Print manifest-defined release targets:

```bash
python -m build_support.release_gate --print-targets
```

Run the complete source gate:

```bash
python -m build_support.quality --skip-build
```

Build the current native candidate:

```bash
python -m build_support.build_candidate
```

Display runtime identity from Python:

```bash
python -c "from product_identity import PRODUCT_DISPLAY_NAME, VERSION, RELEASE_CHANNEL; print(PRODUCT_DISPLAY_NAME, VERSION, RELEASE_CHANNEL)"
```
