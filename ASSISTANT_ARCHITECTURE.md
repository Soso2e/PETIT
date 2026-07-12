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
- Google Calendar: authoritative calendar outside PETIT. PETIT can import a
  configured private iCal/ICS URL read-only into `calendar_events_cache`.
  Writes currently target only PETIT's local calendar provider; Google Calendar
  API/OAuth writes are not implemented.
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
7. Convert write tool calls into an expiring preview. Execute the exact stored
   arguments once only after the user presses the confirmation button.

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

- Google Calendar's Codex/MCP login is isolated from PETIT. ICS read import is
  available, but a Google Calendar API/OAuth write provider is still required.
- Live model quality depends on both configured LM Studio models being loaded and
  the embedding endpoint being available.
- Stalled-project detection is currently evidence-based retrieval and task
  inspection, not a dedicated project-state database.
- Email is not integrated into PETIT.

## Safe extension points

- Add read-only source adapters that normalize into SQLite caches.
- Register calendar write providers behind `backend/calendar_providers.py`.
- Add source freshness timestamps and stale-data warnings.
- Add a weekly review that compares active BRAIN projects, Notion tasks, and
  calendar commitments.
- Add an approval queue for all external writes.
- Add evaluation cases for routing, retrieval relevance, and tool selection.
