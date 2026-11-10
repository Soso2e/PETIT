from backend import delegations


def test_delegations_eligible_antigravity():
    assert "antigravity_cli" in delegations.ELIGIBLE
    assert "antigravity_cli" in delegations.LABELS
    assert "add_coding_repository" in delegations.FRONT_DIRECT
    assert "delete_work_session" in delegations.FRONT_DIRECT


def test_planned_antigravity():
    data = {"antigravity_cli_model": "gemini-3.8-flash-low"}
    assert delegations._planned("antigravity_cli", data) == "gemini-3.8-flash-low"


def test_candidates_includes_antigravity():
    data = {
        "delegate_priority": ["codex", "claude_code"],
        "connected": ["antigravity_cli"],
        "antigravity_cli_enabled": True,
        "antigravity_cli_model": "gemini-3.8-flash-low",
        "brain_transport": "mixed",
        "secrets": {},
        "paid_allowed": [],
    }
    # antigravity_cli が delegate_priority になくても自動補完されて候補になる
    cands = delegations.candidates(data)
    assert "antigravity_cli" in cands
