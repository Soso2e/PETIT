# Sona Core / Linkraft integration removal (v0.34.3, Issue #363)

## Scope

- Removed `backend/sona_core_schedule.py`, `backend/sona_core_add_schedule.py`, their optional dispatch/approval branches, `sona-agent-core` dependency and setup flags.
- Removed Linkraft owner-only client, configuration, project caches/sync logic, candidate link Tools, and per-project refresh adapter.
- Kept the native Renaissance Core's Thread/Turn, current Tool Registry `get_schedule` / `add_schedule`, confirmation API, and existing storage contracts.
- Kept Project Continuity, Notion, GitHub and BRAIN refresh adapters, desktop, ACP/CLI, voice, and all existing data.

## Historical data policy

No database migration, `DROP TABLE`, `DELETE`, or automatic cleanup was introduced.

Previously saved `project_source_links` with `provider='linkraft'` remain unchanged and return `skipped` / `unsupported provider` when refreshed. Similarly, existing `tasks_cache`, `project_events`, `sync_state` and `linkraft_*` tables are retained for historical evidence. Do not drop or purge them without a separately approved inventory, backup, and migration plan.

Old `PETIT_USE_SONA_CORE`, `PETIT_SONA_CORE_*` and `LINKRAFT_*` environment settings are no longer read. Clean them from a private `.env` manually after reviewing local configuration; no credentials were read or changed in this PR. An already-installed `sona-agent-core` package in a venv may remain installed until the user explicitly uninstalls it.

## Verification

```bash
python -m compileall backend tests
python -m unittest -v tests.test_removed_integrations tests.test_project_source_refresh tests.test_project_resume tests.test_notion_adapter_v2 tests.test_calendar_sync tests.test_external_sync
python -m pytest -q tests/test_renaissance_core.py tests/test_pending_actions_router.py tests/test_module_registry.py tests/test_tool_registration.py tests/test_tool_risk_policy.py
```

Then, with a **temporary test DB** and a configured provider, verify: `get_schedule` read; `add_schedule` approve/cancel; Thread/Turn/receipt replay; project resume with both supported and legacy source links; GitHub/Notion/BRAIN fallback on stale sources.

## Limits

CI passing does not prove the user's live SQLite DB contains no remaining Linkraft records or that their configured calendar credentials work. Live-device, external-service and distribution acceptance remain separate. Do not migrate or erase the user's production database automatically.
