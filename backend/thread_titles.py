"""Generate short thread titles via DeepSeek without blocking chat responses."""
from __future__ import annotations

import logging
import re

from fastapi import HTTPException

from . import conversation_store as store, delegations, lmstudio_client, model_routing

log = logging.getLogger(__name__)

MAX_INPUT_CHARS = 500
MAX_TITLE_CHARS = 60
INTERNAL_PREFIX = "[PETIT_INTERNAL_EVENT]"

_SYSTEM_PROMPT = (
    "あなたは会話スレッドのタイトルを作成するアシスタントです。"
    "指示された文章を短い一言のタイトル（15〜30文字程度）に言い直してください。"
    "タイトルの文字列だけを返し、カギ括弧・記号・前置き・補足説明は付けないでください。"
)


def clean_title(raw: str) -> str:
    """Normalize model output into a single-line compact thread title."""
    text = re.sub(r"\s+", " ", str(raw or "")).strip()
    for left, right in (("「", "」"), ("『", "』"), ('"', '"'), ("'", "'")):
        if len(text) >= 2 and text.startswith(left) and text.endswith(right):
            text = text[1:-1].strip()
    text = text.rstrip("。.")
    return text[:MAX_TITLE_CHARS].strip()


def generate_title(message: str) -> str | None:
    """Summarize user text into a short title using DeepSeek Flash."""
    source = str(message or "").strip()
    if not source or source.startswith(INTERNAL_PREFIX):
        return None
    target = model_routing._deepseek_target("deepseek_flash")
    if not target.get("configured"):
        return None
    prompt = f"この文章を一言に言い直してください。：「{source[:MAX_INPUT_CHARS]}」"
    try:
        response = lmstudio_client.chat_completion(
            [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            tools=None,
            temperature=0.2,
            max_tokens=60,
            route="chat",
            target_override=target,
        )
    except Exception as exc:
        log.warning("thread title generation failed type=%s", type(exc).__name__)
        return None
    title = clean_title(response.get("content") or "")
    return title or None


def ensure_thread_title(thread_id: str, message: str) -> str | None:
    """Populate an empty thread title in the background; never overwrite existing titles."""
    try:
        current = store.thread(thread_id)
    except HTTPException:
        return None
    if current.get("title"):
        return None
    if current.get("privacy") == "local_only":
        return None
    if delegations.is_work_thread(thread_id):
        return None
    title = generate_title(message)
    if not title:
        return None
    if store.set_thread_title_if_empty(thread_id, title):
        return title
    return None
