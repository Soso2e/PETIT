from backend.vision_calculations import verify_ratios


def example(**changes):
    values = {"Impressions": "905", "Visits": "720", "Clicks": "465", "Wishlists": "23", "Reported CTR": "51.7%", **changes}
    return [{"attachment_id": "test", "metrics": [{"label": key, "value": value, "unit": ""} for key, value in values.items()]}]


def test_case_a_ratios_and_percentage_point_difference():
    wishlists, clicks = verify_ratios(example())
    assert wishlists["percent"] == "3.1944"
    assert clicks["percent"] == "51.3812"
    assert clicks["difference_percentage_points"] == "0.3188"
    assert "未確認" in clicks["assumption"]


def test_no_guessing_or_division_by_zero():
    assert verify_ratios(example(Visits="0", Impressions="不鮮明")) == []
    assert verify_ratios(example(Visits="7,20", Impressions="NaN")) == []
    assert verify_ratios(example(Visits="720%", Impressions="Infinity")) == []


def test_multiple_periods_ambiguous_and_commas_supported():
    observed = example(Visits="1,000")
    observed[0]["metrics"].append({"label": "Clicks", "value": "40", "unit": ""})
    checked = verify_ratios(observed)
    assert len(checked) == 1 and checked[0]["percent"] == "2.3000"
