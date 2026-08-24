# Planner

The Planner adds a separate way to organize the hacks already present in the
collection. It does not replace collection metadata, ROM files, completion
tracking, or Save Data Sync.

## Planning concepts

Planner information is split into independent concepts so one field does not
need to represent several different intentions.

### Lifecycle status

Lifecycle status describes the player's current relationship with a hack:

- **Planned** — intended for future play.
- **Playing** — actively being played.
- **Paused** — started, but temporarily set aside.
- **Beaten** — the main goal has been cleared.
- **Completed** — the player's chosen full-completion goal has been reached.
- **Dropped** — deliberately stopped without finishing.
- **Archived** — retained for reference but normally excluded from active plans.

### Planning horizon

Planning horizon describes roughly when the player is considering a hack:

- **Someday** — part of the general backlog.
- **Soon** — a nearer-term candidate.
- **Next** — part of the explicitly ordered queue.

Every hack in **Next** receives a one-based queue position. Select one Next row
and use **Move Next Up** or **Move Next Down** to change that order.

The Planner does not store a Low/Normal/High priority. Someday, Soon, and Next
express timing more directly, while custom lists cover broader organization.

### Custom lists

Custom lists are user-defined groups such as `Stream Games`, `Short Hacks`, or
`Recommended by Friends`.

- One hack can belong to multiple lists.
- List names can be changed without breaking membership because each list has a
  stable internal ID.
- Deleting a list removes that membership from every Planner entry, but does not
  remove any hack or ROM from the collection.
- Membership can be added to or removed from multiple selected rows at once.

## Using the Planner page

Open **Planner** from the main navigation. The table shows the current Next
position, title, lifecycle status, planning horizon, custom lists, difficulty,
and hack type.

### Search, filter, and sort

The page can search and filter the projected collection by:

- lifecycle status;
- planning horizon;
- custom list;
- downloaded state;
- free text across collection and Planner display fields.

The shared query layer also supports difficulty and hack-type filters for later
Planner and Wheel interfaces. Values selected within one filter category are
combined as alternatives, while separate categories narrow the result
together.

**Planning order** puts explicitly ordered Next entries first, followed by Soon
and Someday. The page can also retain collection order or sort alphabetically.

### Stage edits before saving

Status, planning horizon, Next ordering, list definitions, and list memberships
are staged in memory first.

1. Select one or more rows.
2. Choose the edit and press the relevant Apply or membership button.
3. Review the updated table and the **Unsaved Planner changes** indicator.
4. Press **Save Changes** to write all staged Planner changes.
5. Press **Discard Changes** to reload the last saved Planner state.

Using **Refresh** reloads current collection records but deliberately keeps
staged Planner changes. Leaving and returning to the Planner after saving shows
the persisted values.

### Optional visibility

Planner is an optional application view over Collection-owned hacks. In
**Settings → Optional Features**, clear **Show Planner in the application** to
hide the Planner navigation page and Planner-specific Wheel refinements.

Hiding Planner does **not** delete `planner_state.json`, make Planner authoritative
for Collection membership, or opt persisted Planner references out of
Collection identity migrations. Re-enabling the view later restores access to
the same Planner-specific state.

## Data and compatibility

Planner data is stored separately in `planner_state.json`. The core collection
continues to use `processed.json`.

- Opening the Planner does not create or rewrite `planner_state.json`.
- Planner edits do not modify `processed.json`.
- The Planner file is written only through **Save Changes**.
- Saves use an atomic replacement and retain the previous file as a backup.
- Unknown top-level and per-entry extension data is preserved.
- Existing collection records do not need to be migrated or rewritten.

A legacy collection record whose existing `completed` value is true is shown as
**Completed** until an explicit Planner lifecycle status is saved. Adding only a
planning horizon or custom-list membership preserves that inferred Completed
status when the first explicit Planner entry is created.

Planner lifecycle timestamps are recorded when relevant milestones are first
reached. Earlier started, beaten, and completed timestamps are retained when a
status later changes.

## Relationship to the Wheel

The current Planner foundation does not yet add a Wheel interface or random
selection. The intended Wheel contract is to randomize from the same filtered
collection the player has chosen.

There is therefore no persistent per-hack `wheel_enabled`, `wheel_eligible`, or
fixed priority field. A later Wheel can combine status, horizon, custom list,
difficulty, type, download state, and search filters freely without maintaining
a second eligibility system that could contradict the Planner.

## Current limitations

- Planner lifecycle status and the collection's existing completion flag are
  separate. Explicit Planner state takes precedence in the Planner view.
- The current page exposes one selected value per filter control, even though
  the shared query layer supports broader combinations for future interfaces.
- Planner timestamps are retained in the data model but are not yet displayed
  or edited directly on the page.
- Random Wheel selection is not included yet.
