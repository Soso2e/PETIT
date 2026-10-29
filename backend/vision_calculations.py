"""Small deterministic checks over observed Steam metrics; no eval or tool calls."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_ALIASES = {"impressions": "impressions", "インプレッション": "impressions", "visits": "visits", "訪問数": "visits",
            "clicks": "clicks", "クリック数": "clicks", "wishlists": "wishlists", "ウィッシュリスト": "wishlists",
            "reportedctr": "ctr", "ctr": "ctr"}


def verify_ratios(images: list[dict]) -> list[dict]:
    results = []
    for image in images:
        values: dict[str, Decimal | None] = {}
        for metric in image.get("metrics", []):
            key = _ALIASES.get(re.sub(r"[\s_:-]", "", metric["label"]).lower())
            if not key:
                continue
            if key in values:
                values[key] = None  # multiple periods/games/duplicate labels are ambiguous
                continue
            text = metric["value"].strip()
            if key == "ctr":
                text = text.removesuffix("%").strip()
            elif "%" in text or "%" in metric.get("unit", ""):
                values[key] = None
                continue
            if not re.fullmatch(r"(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)(?:\.[0-9]+)?", text):
                values[key] = None
                continue
            try:
                value = Decimal(text.replace(",", ""))
                values[key] = value if value <= 10**12 else None
            except InvalidOperation:
                values[key] = None
        for numerator, denominator in (("wishlists", "visits"), ("clicks", "impressions")):
            n, d = values.get(numerator), values.get(denominator)
            if n is None or d is None or d <= 0:
                continue
            percent = n / d * 100
            result = {"attachment_id": image["attachment_id"], "numerator": numerator, "denominator": denominator,
                      "formula": f"{n} / {d} * 100", "percent": str(percent.quantize(Decimal("0.0001"))),
                      "assumption": "表示値が同じ対象・期間で、指定分母に基づく場合の計算。集計定義は未確認。"}
            if numerator == "clicks" and values.get("ctr") is not None:
                result["reported_ctr"] = str(values["ctr"])
                result["difference_percentage_points"] = str((values["ctr"] - percent).quantize(Decimal("0.0001")))
            results.append(result)
    return results
