from backend import main, support_api


ROUTES = [
    ("/api/summarize", "POST", support_api.summarize),
    ("/api/summaries", "GET", support_api.summaries),
    ("/api/vault/sync", "POST", support_api.sync_obsidian_vault),
    ("/api/proactive", "GET", support_api.proactive_opener),
    ("/api/briefing", "GET", support_api.daily_briefing),
    ("/api/calendar/sync", "POST", support_api.sync_calendar),
    ("/api/conversations", "GET", support_api.conversations),
    ("/api/jobs", "GET", support_api.jobs),
    ("/api/jobs/ack", "POST", support_api.acknowledge_jobs),
]


def test_support_routes_are_registered_once_and_owned_by_module() -> None:
    for path, method, endpoint in ROUTES:
        routes = [
            route
            for route in main.app.routes
            if getattr(route, "path", None) == path
            and method in (getattr(route, "methods", None) or set())
        ]
        assert len(routes) == 1, path
        assert routes[0].endpoint is endpoint
        assert endpoint.__module__ == "backend.support_api"


def test_job_ack_requires_session_id() -> None:
    result = support_api.acknowledge_jobs(support_api.JobAck(job_ids=[1, 2], session_id="   "))
    assert result == {"acknowledged": 0, "error": "session_id is required"}
