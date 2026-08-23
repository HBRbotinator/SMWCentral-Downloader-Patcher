# Bulk Collection Import JSON

SMWC v5.1 can import a local JSON document into Collection through the
**Bulk Import Preview** action.

The workflow is deliberately review-first:

1. Select a local `.json` file.
2. Inspect Add / Match / Review outcomes.
3. Resolve every required first-round review decision.
4. Resolve any follow-up metadata conflicts exposed by an explicit match.
5. Inspect the final Create / Update / No Change / Skip application preview.
6. Confirm the exact application-plan SHA-256 before **Apply Import** can write.
7. The final write is performed atomically against `processed.json`.

This document describes the supported version-1 JSON input contract. The example
files in `examples/bulk_collection_import/` are validated by the automated test
suite through the real parser, planner, application preview, confirmed Apply
session, and temporary HackDataManager store.

## File requirements

The local adapter accepts only:

- a regular file whose extension is `.json` (case-insensitive);
- UTF-8 JSON; a UTF-8 BOM is also accepted;
- a non-empty file no larger than 16 MiB;
- standard JSON with no duplicate object keys;
- finite JSON numbers only (`NaN`, `Infinity`, and `-Infinity` are rejected).

The SHA-256 shown by the import workflow is calculated from the exact source
file bytes.

## Versioned top-level shape

Version 1 has an exact top-level shape. No fields may be omitted and no
additional top-level fields are accepted.

```json
{
  "schema": "smwc-bulk-collection-import",
  "version": 1,
  "import_id": "my-import-2026-08",
  "title": "My Collection Import",
  "entries": [],
  "groups": []
}
```

| Field | Type | Rules |
| --- | --- | --- |
| `schema` | string | Must be exactly `smwc-bulk-collection-import`. |
| `version` | integer | Must be exactly `1`; booleans are not accepted as integers. |
| `import_id` | string | 1–128 characters matching `[A-Za-z0-9._:-]+`. |
| `title` | string | Non-empty, already trimmed, at most 512 characters. |
| `entries` | array | Ordered imported hack records. Duplicate `entry_key` values are rejected. |
| `groups` | array | Defines display/import ordering. Every entry must occur exactly once across all groups. |

An empty import is valid: both `entries` and `groups` may be empty.

## Entry shape

Every entry has exactly four fields:

```json
{
  "entry_key": "beginner-hack",
  "title": "Beginner Example",
  "source_references": [
    {
      "source": "smwc",
      "external_id": "12345"
    }
  ],
  "attributes": {
    "authors": ["Example Author"],
    "difficulty": "Kaizo: Beginner",
    "exit_count": 12,
    "release_date": "2026-08-01"
  }
}
```

### `entry_key`

`entry_key` is an import-local identifier. It is not automatically the final
Collection key.

Rules:

- 1–128 characters;
- allowed characters: letters, digits, `.`, `_`, `:`, `-`;
- unique within one import document.

For a create, final Collection-key allocation happens only after identity review
and resolution.

### `title`

The title must be a non-empty already-trimmed string of at most 512 characters.

The title participates in metadata fallback matching. When an authoritative
source reference already matches an existing Collection record, a title mismatch
can still be surfaced for review rather than silently changing identity.

### `source_references`

`source_references` is always an array and may be empty.

Each source reference has exactly:

```json
{
  "source": "smwc",
  "external_id": "12345"
}
```

`source` rules:

- lowercase;
- begins with `a`–`z`;
- remaining characters may use lowercase letters, digits, `.`, `_`, `-`;
- 1–32 characters total.

Examples of syntactically valid source names include:

- `smwc`
- `kaizoff`
- `local`
- `custom-json`
- `community.archive`

`external_id` rules:

- string;
- non-empty;
- already trimmed;
- contains no whitespace;
- at most 256 characters.

The pair `(source, external_id)` is an identity. The same pair may not be
attached to more than one imported entry.

An entry may carry multiple source identities. This is the supported hybrid
case, for example one `smwc` identity plus one `kaizoff` identity.

### SMWCentral IDs and final Collection keys

The generic transport parser treats `external_id` as opaque text, but the v5.1
key allocator has an additional end-to-end rule for `source: "smwc"`:

- the SMWCentral external ID must be decimal;
- its numeric value must be greater than zero;
- leading zeroes are normalized when the final Collection key is allocated.

For example:

```json
{
  "source": "smwc",
  "external_id": "12345"
}
```

creates under Collection key `12345` when the entry is new.

A create with no SMWCentral identity receives a deterministic
`usr_import_<16 lowercase hex>` Collection key instead. This includes
KaizOFF-only and source-less creates.

### Source-less entries

A source-less entry is valid:

```json
"source_references": []
```

Without an authoritative source identity, matching falls back to normalized
metadata. The current identity resolver uses normalized title candidates and,
when present, overlapping normalized `authors`.

This can produce:

- one metadata match;
- an ambiguous Review choice between multiple title candidates;
- a new record when no candidate exists.

For that reason, provide an authoritative source reference whenever one is
available.

## Shared attributes

`attributes` must always be a JSON object.

The import contract accepts finite JSON values, including nested objects and
arrays, but user-owned Collection state is intentionally excluded.

### First-class v5.1 shared fields

These four names map directly to normal v5.1 Collection fields:

| Import attribute | End-to-end type | Stored Collection field |
| --- | --- | --- |
| `authors` | array of trimmed non-empty strings | `authors` |
| `difficulty` | trimmed non-empty string | `current_difficulty` |
| `exit_count` | non-negative integer; boolean is invalid | `exits` |
| `release_date` | trimmed non-empty string, or `""` | `date` |

`authors` also participates in source-less metadata matching.

The importer does not impose a calendar parser on `release_date`; producers
should use one stable representation consistently. The supplied examples use
`YYYY-MM-DD`.

### Custom shared attributes

Other finite JSON attributes may be carried as source-specific/shared metadata,
for example:

```json
"attributes": {
  "authors": ["Hybrid Author"],
  "difficulty": "Kaizo: Intermediate",
  "exit_count": 16,
  "release_date": "2026-07-10",
  "tags": ["short", "vanilla"],
  "source_note": "Example custom shared metadata"
}
```

On persistence, non-core shared attributes are stored under the
`bulk_collection_import.attributes` extension rather than being flattened into
normal Collection fields.

Do not use custom attribute names that collide with local/user-owned Collection
state.

### User-owned/local fields must not be imported

The bulk import is for shared/catalogue metadata. Completion history, local
files, ratings, notes, Planner state, and similar user-owned state are not valid
import payload.

Do not place any of the following in `attributes`:

- `completed`
- `completed_date`
- `completion_date`
- `personal_rating`
- `notes`
- `time_to_beat`
- `file_path`
- `files`
- `additional_paths`
- `download_paths`
- `save_sync_metadata`
- `save_associations`
- `save_paths`
- `rom_paths`
- `provider_extension`
- `local_save_entry`
- `planner`
- `planner_state`
- `obsolete`
- `hack_type`
- `hack_types`
- `folder_name`

Some of these are rejected by the versioned transport contract itself and the
remaining local-only names are rejected by the concrete v5.1 store. Producers
should treat the full list as reserved.

Existing user-owned values are preserved when shared metadata is updated.

## Group shape and ordering

Every group has exactly:

```json
{
  "group_key": "main",
  "title": "Main",
  "entry_keys": [
    "beginner-hack",
    "intermediate-hack"
  ]
}
```

`group_key` follows the same 1–128 character identifier grammar as `entry_key`.

Group titles use the same non-empty, trimmed, maximum-512-character title rule.

`entry_keys` controls order separately from entry metadata.

Across all groups:

- every imported `entry_key` must appear exactly once;
- unknown entry keys are rejected;
- repeating an entry in the same or another group is rejected;
- duplicate `group_key` values are rejected.

Groups are ordering/presentation structure. They do not automatically create
Planner entries or mutate `planner_state.json`.

## Identity and review behavior

The importer deliberately separates identity from metadata merge decisions.

High-level behavior:

- a matching source identity points at that existing Collection record;
- source identities that point at different existing records form a hard
  identity conflict and are not silently merged;
- a source-less entry may match by normalized title/authors;
- multiple plausible metadata candidates require an explicit Review decision;
- a selected existing candidate can expose new metadata conflicts, causing the
  follow-up review round;
- shared-field conflicts require explicit Keep Existing / Use Imported choices;
- Skip is always a non-write outcome.

The final application preview is not produced until all required review rounds
are resolved.

## Atomic Apply and freshness

The final preview contains:

- exact final Collection keys;
- Create / Update / No Change / Skip operations;
- expected shared-state SHA-256 fingerprints for existing targets;
- an SHA-256 for the exact application plan.

**Apply Import** requires explicit confirmation of that exact application-plan
fingerprint.

Immediately before the transaction, the persistence layer verifies that:

- create keys still do not exist;
- Update and No Change targets still have the expected shared-state fingerprint.

If current shared Collection state differs from the reviewed preview, Apply
fails rather than silently writing against stale data.

A successful write uses a temporary file, backup, fsync, and atomic replacement
of `processed.json`.

Bulk import does not modify Planner state.

## Examples

### Basic SMWCentral import

See:

`examples/bulk_collection_import/basic-smwc.json`

This demonstrates two new SMWCentral-backed entries. Against an empty
Collection, their final keys are `12345` and `67890`.

### Hybrid/source-neutral import

See:

`examples/bulk_collection_import/hybrid.json`

This demonstrates:

- one entry carrying both SMWCentral and KaizOFF identities;
- one KaizOFF-only entry;
- one source-less entry;
- custom shared extension attributes;
- multiple ordered groups.

Against an empty Collection, the hybrid SMWCentral entry uses key `54321`; the
other two creates receive deterministic `usr_import_...` keys.

## Minimal checklist for producers

Before handing a file to SMWC v5.1:

1. Use schema `smwc-bulk-collection-import`, version `1`.
2. Emit exactly the documented object fields.
3. Keep IDs and titles trimmed.
4. Keep each `(source, external_id)` pair globally unique.
5. Use positive decimal strings for `smwc` external IDs.
6. Put only shared/catalogue metadata in `attributes`.
7. Put every entry exactly once in `groups[*].entry_keys`.
8. Save as valid UTF-8 `.json` under 16 MiB.
9. Expect the user to review ambiguous identity or metadata conflicts.
10. Do not assume preview means write: Apply requires separate explicit
    confirmation and final freshness checks.
