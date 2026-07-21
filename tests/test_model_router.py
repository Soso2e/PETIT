from backend import model_router


def test_casual_problem_phrase_stays_on_chat() -> None:
    route = model_router.choose("今日は問題ないよ")

    assert route["kind"] == "chat"
    assert route["reasons"] == ["simple_conversation"]


def test_casual_improvement_report_stays_on_chat() -> None:
    route = model_router.choose("会話しやすさはかなり改善した")

    assert route["kind"] == "chat"


def test_explicit_improvement_request_uses_agent() -> None:
    route = model_router.choose("PETITの改善案を考えて")

    assert route["kind"] == "agent"
    assert "explicit_reasoning" in route["reasons"]


def test_domain_reasoning_request_uses_agent() -> None:
    route = model_router.choose("このエージェント設計を評価して")

    assert route["kind"] == "agent"
    assert "domain_reasoning" in route["reasons"]


def test_multi_part_request_uses_agent() -> None:
    route = model_router.choose("1。2。3。4。5。6。7。8。9。")

    assert route["kind"] == "agent"
    assert "multi_part" in route["reasons"]
