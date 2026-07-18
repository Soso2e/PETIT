# BRAIN Project Mapping

PETIT can connect existing Obsidian/BRAIN Markdown notes to one internal project. Markdown remains the canonical knowledge source; PETIT stores only confirmation candidates, a bounded resume cache, freshness, and idempotent update events.

## Configuration

```env
PETIT_OBSIDIAN_VAULT_DIRS=C:\path\to\YourVault
PETIT_BRAIN_PROJECT_EXCERPT_CHARS=1200
PETIT_BRAIN_PROJECT_MAX_HEADINGS=12
```

Multiple vaults use the same separator as `PETIT_OBSIDIAN_VAULT_DIRS`. The source identity stored in `project_source_links` is:

```text
provider = brain
external_id = vault:<configured index>:<relative Markdown path>
```

The absolute vault path is not stored in the source identity.

## Candidate discovery

PETIT can:

- search configured vaults with an internal project's confirmed name and aliases
- inspect one explicitly named relative `.md` path
- show pending candidates
- link or ignore a candidate after approval

Similarity creates a candidate only. It never creates a trusted relation automatically.

Examples:

```text
BRAINノート候補を探して
BRAINノート候補を見せて
BRAINの「Projects/PETIT.md」を候補として確認して
BRAINノート候補をPETITへ紐付けて
```

Candidate linking and ignoring use the existing approval preview.

## Path safety

Candidate discovery and refresh reuse the existing Vault boundary:

- only configured vault roots
- relative Markdown paths only
- no absolute paths or `..`
- no `_private`, `.obsidian`, attachment, cache, trash, or other excluded folders
- no non-Markdown files
- no files larger than the configured indexing safety limit
- no Vault escape through resolved paths

Existing `edit_brain_note` behavior is unchanged. Project mapping does not modify Markdown.

## Project cache

For a confirmed note PETIT stores:

- internal project id
- vault index and relative path
- title and bounded headings
- SHA-256 content hash
- source modified time and size
- bounded excerpt
- last successful sync state

The default cache excerpt is at most 1,200 characters. Project resume reads at most three notes and renders an even shorter excerpt. Full Markdown is never inserted into the deterministic resume response.

## Refresh semantics

Immediately before project resume, PETIT refreshes only source links that match the selected internal project and satisfy:

```text
provider = brain
status = active
confirmed_at IS NOT NULL
```

Unconfirmed candidates, removed links, and notes linked to another project are not read.

Every refresh reads and hashes the Markdown content. This avoids missing same-size edits made within the same filesystem timestamp second. An unchanged hash creates no project event. A changed hash creates one idempotent:

```text
provider = brain
event_type = brain_note_updated
```

The event is an external knowledge update. It never overwrites the user-confirmed project checkpoint.

## Missing or unreadable notes

If a confirmed note disappears or becomes unreadable:

- the previous bounded cache remains available
- source freshness becomes stale
- project resume continues from the saved checkpoint and cache
- the response states that BRAIN refresh failed

## Verification

```bash
python -m unittest \
  tests.test_brain_candidate_discovery \
  tests.test_brain_project_mapping \
  tests.test_brain_project_routing \
  tests.test_project_source_refresh \
  tests.test_project_resume
python -m compileall backend tests
```
