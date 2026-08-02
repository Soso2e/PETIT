from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


def test_app_shell_loads_life_map_assets():
    source = (FRONTEND / "app_shell.js").read_text(encoding="utf-8")

    assert 'loadStylesheet("/static/life-map.css", "life-map-style")' in source
    assert 'loadScript("/static/life-map.js", "life-map-script")' in source
    assert 'data-view-panel="universe"' in source


def test_life_map_uses_existing_project_and_task_focus_hooks():
    source = (FRONTEND / "life-map.js").read_text(encoding="utf-8")

    assert 'const MAP_SELECTOR = "#constellation-grid"' in source
    assert 'classList?.contains("constellation-card")' in source
    assert 'querySelector(".constellation-card__header")' in source
    assert 'querySelectorAll(":scope > .universe-task")' in source
    assert "MutationObserver" in source
    assert "life-map__connection" in source
    assert "へフォーカス" in source


def test_life_map_has_mobile_and_reduced_motion_styles():
    source = (FRONTEND / "life-map.css").read_text(encoding="utf-8")

    assert ".constellation-grid.life-cosmos-map" in source
    assert ".life-map__connection.is-active" in source
    assert ".life-star-system .universe-task.life-task-star" in source
    assert "@media (max-width: 640px)" in source
    assert "@media (prefers-reduced-motion: reduce)" in source
