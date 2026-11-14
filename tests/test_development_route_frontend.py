from pathlib import Path


FRONTEND = Path(__file__).resolve().parents[1] / "frontend"


def read(name):
    return (FRONTEND / name).read_text(encoding="utf-8")


def test_develop_starts_jobs_inside_the_main_tab():
    universe = read("universe.html")
    assert 'data-view-panel="development"' in universe and 'id="development-request"' in universe
    assert 'name="repository"' in universe and 'name="model_key"' in universe
    assert '<option value="medium" selected>Effort: Medium</option>' in universe
    assert "指定なし（PC内の全ファイルを見る）" in universe
    assert '/static/development.html' not in universe
    script = read("development.js")
    assert 'api("/jobs/start", "POST"' in script
    assert 'api("/usage")' in script and 'api("/config/root", "POST"' in script


def test_chat_and_develop_share_the_proposal_and_host_action_controls():
    assert "development_job_id" in read("universe-app.js") and "development_job_id" in read("app.js")
    script = read("development.js")
    assert 'decide("/approve", "この内容で開発を依頼する")' in script
    assert 'decide("/cancel", "キャンセル")' in script
    assert 'item.status === "proposed" && job.status === "waiting_approval"' in script
    assert 'textContent = value' in script and 'innerHTML' not in script


def test_claude_auth_actions_and_update_guidance_are_present():
    page = read("setup.html")
    for button in ("claude-code-login", "claude-code-diagnose", "claude-code-logout"):
        assert f'id="{button}"' in page
    script = read("setup.js")
    assert "claude update" in script
    assert "api('/claude-code/auth/login', 'POST')" in script
    assert "api('/claude-code/auth/logout', 'POST')" in script
