"""User-run official SDK probe. Default mode constructs config without networking.

No PETIT imports, credential-cache access, API substitution, or real domain writes.
Live mode uses loopback LM Studio by default. Gemini mode requires explicit selection and a key.
"""
from __future__ import annotations

import argparse
import asyncio
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import tempfile
import time
import uuid
from urllib.parse import urlsplit

SDK_VERSION = "0.1.22"


def make_config(root: Path, *, api_key: str = "", model: str | None = None,
                conversation_id: str | None = None, resume: bool = False,
                tools: list | None = None, backend: str = "local",
                base_url: str = "http://127.0.0.1:1234/v1"):
    from google.antigravity import CapabilitiesConfig, LocalAgentConfig, LocalOpenAIAgentConfig
    from google.antigravity.hooks import policy
    from google.antigravity.types import BuiltinTools, SessionContinuationMode

    if importlib.metadata.version("google-antigravity") != SDK_VERSION:
        raise ValueError("unsupported_sdk_version")
    custom = list(tools or [])
    options = dict(
        model=model,
        system_instructions="Use only the provided synthetic data and tools. Follow the user's requested output exactly.",
        capabilities=CapabilitiesConfig(enabled_tools=[BuiltinTools.FINISH]),
        policies=[policy.deny("*"), policy.allow("finish"),
                  *[policy.allow(fn.__name__) for fn in custom]],
        tools=custom, mcp_servers=[], skills_paths=[], inline_skills=[],
        subagents=[], triggers=[], workspaces=[str(root / "workspace")],
        app_data_dir=str(root / "app"), save_dir=str(root / "sessions"),
        conversation_id=conversation_id,
        session_continuation_mode=SessionContinuationMode.RESUME if resume else None,
    )
    if backend == "local":
        parsed = urlsplit(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1"} or parsed.username or parsed.password:
            raise ValueError("loopback_only")
        return LocalOpenAIAgentConfig(base_url=base_url, **options)
    if backend != "gemini":
        raise ValueError("unsupported_backend")
    return LocalAgentConfig(api_key=api_key, vertex=False, **options)


def summarize_usage(response) -> dict | None:
    usage = response.usage_metadata
    if usage is None:
        return None
    return {name: getattr(usage, name, None) for name in (
        "prompt_token_count", "candidates_token_count", "total_token_count",
        "cached_content_token_count", "thoughts_token_count")}


async def ask(agent, prompt: str, expected: str, timeout: float) -> dict:
    started = time.monotonic()

    async def consume():
        response = await agent.chat(prompt)
        pieces = [piece async for piece in response]
        text = await response.text()
        return {"matched": text.strip() == expected,
                "stream_matches_text": "".join(pieces) == text,
                "stream_chunks": len(pieces), "usage": summarize_usage(response),
                "stop_reason": str(response.stop_reason)}

    result = await asyncio.wait_for(consume(), timeout)
    return {**result, "latency_seconds": round(time.monotonic() - started, 3)}


async def live_probe(root: Path, api_key: str, model: str | None, timeout: float,
                     backend: str = "local", base_url: str = "http://127.0.0.1:1234/v1") -> dict:
    from google.antigravity import Agent

    expected = "probe-" + uuid.uuid4().hex
    tool_calls = []

    def get_probe_fact() -> str:
        """Return the single synthetic probe fact. This has no external side effects."""
        tool_calls.append("get_probe_fact")
        return expected

    config = make_config(root, api_key=api_key, model=model, tools=[get_probe_fact], backend=backend, base_url=base_url)
    started = time.monotonic()
    async with asyncio.timeout(timeout):
        async with Agent(config) as agent:
            startup_seconds = time.monotonic() - started
            first = await ask(agent, "Call get_probe_fact and reply with only its exact returned value.", expected, timeout)
            second = await ask(agent, "Repeat the fact returned by get_probe_fact in the previous turn. Only the value; do not call any tools.", expected, timeout)
            conversation_id = agent.conversation_id
    if not conversation_id:
        raise ValueError("missing_conversation_id")
    # Resume only this fresh synthetic conversation, never a user's existing one.
    resumed_config = make_config(root, api_key=api_key, model=model,
                                 conversation_id=conversation_id, resume=True, backend=backend, base_url=base_url)
    async with asyncio.timeout(timeout):
        async with Agent(resumed_config) as agent:
            third = await ask(agent, "Repeat the synthetic fact from the previous conversation turns. Only the value.", expected, timeout)
            same_id = agent.conversation_id == conversation_id
    passed = (all(x["matched"] and x["stream_matches_text"] for x in (first, second, third))
              and tool_calls == ["get_probe_fact"] and same_id)
    return {"status": "passed" if passed else "failed", "network_invoked": True,
            "startup_seconds": round(startup_seconds, 3),
            "conversation_id_retained": same_id, "synthetic_tool_calls": len(tool_calls),
            "turns": [first, second, third], "petit_brain_connected": False}


def run(*, live: bool = False, model: str | None = None, timeout: float = 60,
        backend: str = "local", base_url: str = "http://127.0.0.1:1234/v1") -> dict:
    report = {"sdk_version": SDK_VERSION, "mode": "live" if live else "offline",
              "network_invoked": False, "petit_brain_connected": False,
              "issue_349_complete": False, "backend": backend, "model": model}
    try:
        if not 0 < timeout <= 300:
            raise ValueError("timeout_out_of_range")
        with tempfile.TemporaryDirectory(prefix="petit-antigravity-probe-") as temp:
            root = Path(temp)
            for name in ("workspace", "app", "sessions"):
                (root / name).mkdir()
            if not live:
                config = make_config(root, api_key="synthetic-offline-not-a-key", model=model, backend=backend, base_url=base_url)
                report.update(status="offline_config_validated",
                              enabled_builtins=[tool.value for tool in config.capabilities.enabled_tools],
                              custom_tools=len(config.tools), session_persistence="not_executed")
            elif backend == "gemini" and not os.getenv("GEMINI_API_KEY", "").strip():
                report.update(status="skipped", reason="missing_sdk_api_key")
            else:
                report.update(asyncio.run(live_probe(root, os.getenv("GEMINI_API_KEY", "") if backend == "gemini" else "",
                                                    model, timeout, backend, base_url)))
    except (ImportError, importlib.metadata.PackageNotFoundError):
        report.update(status="skipped", reason="sdk_not_installed")
    except (TimeoutError, asyncio.CancelledError):
        report.update(status="failed", reason="timeout_or_cancel", network_invoked=None if live else False)
    except KeyboardInterrupt:
        report.update(status="failed", reason="user_interrupted", network_invoked=None if live else False)
    except Exception as exc:
        # SDK/provider error strings can include prompts, URLs, or credentials.
        report.update(status="failed", reason="sdk_error", error_type=type(exc).__name__,
                      network_invoked=None if live else False)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly send only synthetic probe data through the SDK (API billing may apply)")
    parser.add_argument("--model")
    parser.add_argument("--backend", choices=("local", "gemini"), default="local")
    parser.add_argument("--base-url", default="http://127.0.0.1:1234/v1")
    parser.add_argument("--timeout", type=float, default=60)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    # Keep third-party Python exception logs out of probe output.
    logging.disable(logging.CRITICAL)
    report = run(live=args.live, model=args.model, timeout=args.timeout, backend=args.backend, base_url=args.base_url)
    encoded = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(encoded)
    print(encoded, end="")
    return 0 if report["status"] in {"passed", "offline_config_validated"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
