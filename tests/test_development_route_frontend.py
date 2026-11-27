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
    assert 'title: ""' in script and 'input.goal.slice(0, 120)' not in script
    assert 'api("/usage")' in script and 'api("/config/root", "POST"' in script
    assert 'id="development-provider-usage"' in universe
    assert "renderProviderUsage" in script
    assert ".development-usage-strip" in read("development.css")


def test_chat_and_develop_share_the_proposal_and_host_action_controls():
    assert "development_job_id" in read("universe-app.js") and "development_job_id" in read("app.js")
    script = read("development.js")
    assert 'decide("/approve", "この内容で開発を依頼する")' in script
    assert 'decide("/cancel", "キャンセル")' in script
    assert 'item.status === "proposed" && job.status === "waiting_approval"' in script
    assert 'textContent = value' in script and 'innerHTML' not in script
    assert 'PetitMarkdown?.renderTo' in script
    assert 'PetitChatMotion?.createStreamingController' in script
    assert 'addEventListener("draft"' in script


def test_claude_auth_actions_and_update_guidance_are_present():
    page = read("setup.html")
    for button in ("claude-code-login", "claude-code-diagnose", "claude-code-logout"):
        assert f'id="{button}"' in page
    script = read("setup.js")
    assert "claude update" in script
    assert "api('/claude-code/auth/login', 'POST')" in script
    assert "api('/claude-code/auth/logout', 'POST')" in script


def test_stopped_job_offers_resume_in_the_same_thread():
    script = read("development.js")
    for status in ("interrupted", "failed", "cancelled", "checks_failed"):
        assert status + ":" in script.split("const resumeGoals = {")[1].split("};")[0]
    # Only the latest turn offers it, and it reuses the thread and the job's model selection.
    assert "latest && resumeGoals[job.status] && currentThread" in script
    assert "thread_id: threadId, model_key: job.selection?.model_key" in script


def test_notification_link_opens_its_develop_thread_once():
    script = read("development.js")
    assert 'url.searchParams.get("dev_thread")' in script and 'url.searchParams.delete("dev_thread")' in script
    assert script.count("openLinkedThread();") == 2


def test_chat_proposal_passes_the_request_as_written():
    from backend.tools import coding  # noqa: F401 - registers the tool
    from backend import tools, delegations
    description = next(item["function"]["description"] for item in tools.openai_tools_schema()
                       if item["function"]["name"] == "propose_development_job")
    assert "原文のまま" in description and "足さない" in description
    assert "原文のまま goal" in delegations.FRONT_HINT


def test_develop_thread_long_press_context_menu_and_motion():
    script = read("development.js")
    assert "attachThreadLongPress" in script
    assert "openThreadContextMenu" in script
    assert '"review_later"' in script and '"completed"' in script
    assert "スレッド名変更" in script and "あとで確認" in script and "削除" in script
    assert 'mutateThread(data.thread_id, "DELETE")' in script
    assert "innerHTML" not in script


def test_develop_reply_exposes_copy_button():
    script = read("development.js")
    assert "PetitMarkdown?.createCopyButton" in script
    assert "development-reply-copy" in script

    css = read("development.css")
    assert ".development-context-menu" in css
    assert "devMenuSpringIn" in css
    assert "prefers-reduced-motion: reduce" in css


def test_island_click_opens_running_thread_without_lock_collision():
    script = read("development.js")
    assert "let threadRequestSeq = 0;" in script
    assert "if (reqSeq !== threadRequestSeq) return;" in script
    assert 'threads.find((item) => item.latest_job?.status === "running")' in script


def test_develop_threads_collapse_after_five_into_toggle_with_preserved_state():
    script = read("development.js")
    assert "const VISIBLE_THREAD_LIMIT = 5;" in script
    assert "partitionVisibleThreads" in script
    assert "renderCollapsibleThreadList" in script
    assert "development-threads-more" in script
    assert "expandedThreadGroups" in script
    assert "過去のスレッドを表示" in script and "過去のスレッドを折りたたむ" in script
    assert "innerHTML" not in script

    css = read("development.css")
    assert ".development-threads-more" in css
    assert ".development-threads-more-list" in css


def test_active_developing_threads_stay_visible_and_highlighted_in_thread_lists():
    universe = read("universe.html")
    assert "<h2>開発中・確認待ち</h2>" in universe

    script = read("development.js")
    priority_block = script.split("const attentionPriority = {")[1].split("};")[0]
    for status in ("waiting_approval", "running", "queued", "proposed", "ready_for_review", "checks_failed"):
        assert status + ":" in priority_block
    assert "const isActiveThread = (item) => active.has(item?.latest_job?.status);" in script
    assert "if (visible.length < limit || isActiveThread(item)) visible.push(item);" in script
    assert 'control.dataset.active = "true";' in script
    assert 'activeBadge.className = "development-active-badge";' in script

    css = read("development.css")
    assert ".development-active-badge" in css
    assert '.development-thread-card[data-active="true"]' in css
    assert '.development-active-badge[data-status="running"]::before' in css


def test_develop_goal_submits_on_enter_with_ime_guard():
    script = read("development.js")
    assert 'form.elements.goal.addEventListener("compositionstart"' in script
    assert 'form.elements.goal.addEventListener("compositionend"' in script
    assert 'form.elements.goal.addEventListener("keydown"' in script
    assert 'window.matchMedia("(pointer: coarse)")' in script
    assert "if (isCoarsePointer()) return;" in script
    assert "event.isComposing || event.keyCode === 229" in script
    assert "if (event.key !== \"Enter\" || event.shiftKey) return;" in script
    assert "form.requestSubmit();" in script
