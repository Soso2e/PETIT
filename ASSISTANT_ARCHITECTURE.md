# PETIT Assistant Architecture

## Goal

PETIT is a source-aware personal assistant, not a generic chat wrapper. It should
read only the context needed for the current turn, combine personal knowledge,
tasks, schedule, recent conversation, and the active project's verified state,
and propose a concrete next action.

## Source roles

- BRAIN (Obsidian Markdown): canonical personal knowledge, decisions, project
  notes, and reusable context. PETIT retrieves a small ranked set; it never puts
  the whole vault into one prompt. `_private`, attachments, and Obsidian internals
  are excluded from indexing.
- Notion: canonical editable personal project and task data. The Phase 2 adapter
  preserves project/task Relations, assignees, hierarchy, blockers, source IDs,
  and separate project/task freshness. Name similarity creates a candidate only;
  an internal project mapping requires confirmation.
- Linkraft: canonical Life is Tech / student project state. PETIT reads only
  projects owned by the configured Linkraft user through a dedicated read-only
  bearer identity. Confirmed projects use per-project delta cursors.
- GitHub: evidence that code, tests, pull requests, or deployments changed. A
  commit alone never proves full completion.
- Google Calendar: authoritative calendar outside PETIT. PETIT can import a
  configured private iCal/ICS URL read-only into `calendar_events_cache`.
  Writes currently target only PETIT's local calendar provider; Google Calendar
  API/OAuth writes are not implemented.
- PETIT conversation: canonical record of confirmed intent, reasoning, completion
  scope, and the user's own explanation of what happened.
- SQLite: local structured cache plus PETIT-owned project identity, source mapping,
  active state, approval receipts, checkpoints, and events.
- Chroma: replaceable search index, never the canonical knowledge source.

## Project Continuity Engine

### Internal identity

Every project receives one stable PETIT `projects.id`. Human names and alternative
phrases live in `project_aliases`; the same normalized alias may belong to multiple
projects. Alias collisions return candidates and never silently choose one.

External identities live in `project_source_links` with provider, external id,
URL, metadata, status, and confirmation timestamp. Candidate links are not trusted
until confirmed. Active links must be explicitly removed before they can be
reassigned to another project.

### Active state and memory relation

- `active_project_state`: current project per PETIT user.
- `project_checkpoints`: last confirmed stage, summary, next action, blockers,
  evidence, unverified work, session bounds, and source conversation ids.
- `episode_project_links`: many-to-many relation between conversation episodes and
  projects, including relation type, confidence, and confirmation state.
- `project_events`: approved PETIT-side project changes plus normalized external
  source changes.
- `project_completion_drafts`: short-lived clarification state for vague completion.
- `project_write_receipts`: idempotency receipts for confirmed project creation and
  alias writes.

### Deterministic conversation path

Before ordinary chat or tool routing, PETIT checks a narrow set of project intents:

1. confirmed project registration or alias command
2. pending or explicit project completion report
3. explicit project start, resume, or switch
4. otherwise continue through the normal chat/tool path

This path uses SQLite and Python rules only. It remains available when LM Studio is
stopped and never loads every memory, Vault note, or external source.

### Start and resume

For `Linkraftやる`, `PETITに戻る`, or a confirmed alias, PETIT resolves one project,
updates `active_project_state`, refreshes only that project's confirmed sources,
and builds a bounded `ProjectResumeContext` in this priority order:

1. project checkpoint
2. recent approved or normalized project events
3. recent confirmed linked episodes
4. compatible legacy handoff note
5. freshness of confirmed external source links

The renderer keeps verified items, unverified items, blockers, and next action
separate. Its reference counts are exposed in `model_route.resume_references`.

### Confirmed source refresh

Immediately before resume context is read, PETIT selects only `project_source_links`
rows where the internal project matches, `status=active`, and `confirmed_at` is set.

- Notion runs at most once for the resume turn and keeps its normal TTL-aware,
  independent project/task synchronization.
- Linkraft refreshes only the selected project's confirmed external IDs. It does
  not use the broad all-linked-project sync and retains a cursor per external ID.
- Unconfirmed candidates, removed links, other projects, and unsupported providers
  are never sent to an adapter.
- One provider failure does not stop another provider or checkpoint-based resume.
- Previous successful caches remain available and are disclosed as stale.
- The refresh result records attempted, failed, and skipped providers without an LLM.

Detailed behavior is documented in [`docs/project_source_refresh.md`](docs/project_source_refresh.md).

### Completion

A vague `終わった` creates a short-lived clarification draft instead of changing
state. PETIT distinguishes implementation, automated tests, real UI verification,
deployment, production verification, pause, blocker, and full completion. It does
not infer earlier verification stages from a later operational action: for example,
`デプロイした` is not evidence that automated tests or browser verification ran.

Once the user provides enough scope, PETIT creates an exact pending-action preview.
Only approval writes the checkpoint and a `provider=petit` event. The write is
idempotent, links to the saved conversation when available, and preserves prior
source conversation ids.

### Registration and aliases

Unknown explicit names are never auto-created. PETIT proposes a confirmed
`create_internal_project` action, then creates and optionally activates the project
once. Existing names offer activation instead of duplication. Alias writes are also
confirmed; collisions are disclosed and remain ambiguous during future routing.

## Turn flow

1. Check the deterministic Project Continuity path.
2. For an explicit project resume, refresh only its confirmed external sources.
3. Classify the remaining request locally.
4. Route a short simple turn to the chat model; route tools, planning,
   personal-history work, analysis, and implementation requests to the agent model.
5. Search BRAIN and memory only when the turn can benefit from personal context.
6. For planning turns, refresh Notion read-only and load bounded task/calendar
   context.
7. Let the selected model use only related tools if it is an agent turn.
8. Return a short answer with a next action when useful.
9. Convert write tool calls into an expiring preview. Execute the exact stored
   arguments once only after the user presses the confirmation button.

## Model routing

- `PETIT_CHAT_BASE_URL` / `PETIT_CHAT_MODEL` / `PETIT_CHAT_API_KEY`: short
  conversation and natural-language presentation endpoint.
- `PETIT_AGENT_BASE_URL` / `PETIT_AGENT_MODEL` / `PETIT_AGENT_API_KEY`: tool
  calling, multi-step reasoning, BRAIN/Notion/calendar work, analysis, and
  implementation requests.
- Project Continuity's start/end/register/resume and confirmed-source refresh path
  does not require a model.
- Routing is intent/source based, not a raw message/history length threshold.
- Agent `/models` health is cached. If it is unavailable, only a read result
  that PETIT has already obtained safely may be presented by Chat. Tool choice
  and all writes remain unavailable rather than being silently skipped.
- `/api/health` and each response's `model_route.observability` expose route,
  model endpoint ID, tool list, calls, freshness, fallback and elapsed time.

All Chat/Agent settings fall back to their `PETIT_LM_*` counterpart, so a
one-model setup remains valid and an Agent can instead run on another PC/GPU.

## Phase boundary

### Phase 1

- internal project identity and aliases
- confirmable source links
- active project and checkpoints
- project-scoped conversation episode relation
- confirmed completion events
- start, finish, switch, resume, registration, and alias conversation flows

### Phase 2 implemented

- Notion project/task Relation adapter and confirmation-first mappings
- Linkraft owner-only read API and PETIT adapter
- external project events and per-source freshness
- confirmed-source refresh immediately before project resume

### Phase 2 remaining

- scattered BRAIN candidate discovery with confirmation
- GitHub commit/PR/test/deploy evidence
- project-aware morning briefing and cross-project prioritization

## Current limitations

- Automated tests and compile checks cover the continuity and source adapters, but
  real service credentials and browser approval/cancel/restart E2E remain required.
- GitHub evidence and BRAIN project mappings are not yet connected to the internal
  project IDs.
- Google Calendar's Codex/MCP login is isolated from PETIT. ICS read import is
  available, but a Google Calendar API/OAuth write provider is still required.
- Live model quality depends on both configured LM Studio models being loaded and
  the embedding endpoint being available.
- Email is not integrated into PETIT.

## Safe extension points

- Add read-only source adapters that normalize into project-scoped SQLite caches
  and `project_events`.
- Register calendar write providers behind `backend/calendar_providers.py`.
- Preserve source freshness timestamps and stale-data warnings.
- Add a weekly review that compares active projects, Notion tasks, Linkraft state,
  GitHub evidence, BRAIN notes, and calendar commitments.
- Route every external write through scoped approval, idempotency, and audit.
- Add evaluation cases for routing, retrieval relevance, source conflicts, and
  tool selection.
