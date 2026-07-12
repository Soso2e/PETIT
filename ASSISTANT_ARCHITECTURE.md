# PETIT Assistant Architecture

## Goal

PETIT is a source-aware personal assistant, not a generic chat wrapper. It should
read only the context needed for the current turn, combine personal knowledge,
tasks, schedule, and recent conversation, and propose a concrete next action.

## Source roles

- BRAIN (Obsidian Markdown): canonical personal knowledge, decisions, project
  notes, and reusable context. PETIT retrieves a small ranked set; it never puts
  the whole vault into one prompt. `_private`, attachments, and Obsidian internals
  are excluded from indexing.
- Notion: canonical editable task list. Relevant planning turns perform a
  read-only sync into SQLite before reasoning.
- Google Calendar: authoritative calendar outside PETIT, but not yet connected
  to the PETIT process. PETIT currently reads `calendar_events_cache` and must
  say when an empty cache is not proof of an empty calendar.
- SQLite: local structured cache and PETIT-owned state.
- Chroma: replaceable search index, never the canonical knowledge source.

## Turn flow

1. Classify the request locally.
2. Route a short simple turn to the chat model; route tools, long context,
   multi-part requests, planning, and personal-history work to the agent model.
3. Search BRAIN and memory only when the turn can benefit from personal context.
4. For planning turns, refresh Notion read-only and load bounded task/calendar
   context.
5. Let the selected model use tools if it is an agent turn.
6. Return a short answer with a next action when useful.
7. Suggest task or record candidates from the conversation, but do not write to
   external services without explicit confirmation.

## Model routing

- `PETIT_CHAT_MODEL`: short conversation and natural-language presentation.
- `PETIT_AGENT_MODEL`: tool calling, long requests, multi-step reasoning,
  BRAIN/Notion/calendar work, analysis, and implementation requests.
- When the models differ, the chat model presents the agent draft without changing
  facts, warnings, unknowns, or next actions.
- `PETIT_AGENT_MESSAGE_CHARS` and `PETIT_AGENT_HISTORY_CHARS`: deterministic
  length thresholds.

Both model variables fall back to `PETIT_LM_MODEL`, so a one-model setup remains
valid.

## Current limitations

- Google Calendar's Codex/MCP login is isolated from PETIT. A read-only calendar
  sync adapter with its own OAuth or export source is still required.
- Live model quality depends on both configured LM Studio models being loaded and
  the embedding endpoint being available.
- Stalled-project detection is currently evidence-based retrieval and task
  inspection, not a dedicated project-state database.
- Email is not integrated into PETIT.

## Safe extension points

- Add read-only source adapters that normalize into SQLite caches.
- Add source freshness timestamps and stale-data warnings.
- Add a weekly review that compares active BRAIN projects, Notion tasks, and
  calendar commitments.
- Add an approval queue for all external writes.
- Add evaluation cases for routing, retrieval relevance, and tool selection.
