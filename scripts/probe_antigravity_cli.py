"""Standalone direct CLI diagnostic; never imported by PETIT's runtime.

Default: version only. --live explicitly sends synthetic prompts in a temporary
workspace through the official CLI. It neither installs nor logs in the user.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from backend.antigravity_cli import Protocol, error_category, executable, status, MAX_BYTES


def stop_tree(process):
    if os.name == "nt":
        # PID is from this owned Popen only. No name-based termination.
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"],
                       stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=10)
    else:
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    if process.poll() is None:
        process.kill()
    process.wait(timeout=10)


def invoke(command, cwd, *, timeout=60, cancel=lambda: False):
    """Bounded direct subprocess with tree cleanup and no inherited API-key auth."""
    env = {k: v for k, v in os.environ.items() if not (
        k.upper().endswith(("API_KEY", "API_TOKEN")) or k.upper() in {
            "GOOGLE_APPLICATION_CREDENTIALS", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_CLOUD_PROJECT",
            "GOOGLE_CLOUD_LOCATION", "ANTHROPIC_AUTH_TOKEN", "GOOGLE_API_USE_MTLS_ENDPOINT"})}
    with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
        process = subprocess.Popen(command, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                   stdout=stdout, stderr=stderr,
                                   start_new_session=os.name != "nt",
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0)
        deadline = time.monotonic() + timeout
        try:
            while process.poll() is None:
                if cancel():
                    raise InterruptedError("cancelled")
                if time.monotonic() >= deadline:
                    raise TimeoutError("timeout")
                if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > MAX_BYTES:
                    raise ValueError("cli_output_limit")
                time.sleep(.03)
            if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > MAX_BYTES:
                raise ValueError("cli_output_limit")
            stdout.seek(0); stderr.seek(0)
            return process.returncode, stdout.read(MAX_BYTES).decode("utf-8", "replace"), stderr.read(MAX_BYTES).decode("utf-8", "replace")
        except BaseException:
            stop_tree(process)
            raise


def run(*, live=False):
    report = {**status(), "evidence": "direct_cli_probe", "scope": "synthetic_workspace_only",
              "checked_at_utc": datetime.now(timezone.utc).isoformat(),
              "subscription_quota_used": "unknown", "child_api_key_policy": "remove",
              "petit_integration_verified": False, "checks": []}
    binary = executable()
    if not binary:
        return {**report, "status": "skipped", "reason": "cli_not_installed", "network_invoked": False}
    # Only the official binary from PATH/official install location is invoked.
    with tempfile.TemporaryDirectory(prefix="petit-agy-direct-") as temporary:
        root = Path(temporary)
        (root / "README.md").write_text("# PETIT direct CLI fixture\nREAD_EVIDENCE_4f99: This is synthetic documentation.\n", encoding="utf-8")
        try:
            code, output, _ = invoke([binary, "--version"], root, timeout=10)
            version = re.search(r"\b\d+\.\d+\.\d+(?:[-+][a-zA-Z0-9.-]+)?\b", output)
            report["version"] = version[0] if code == 0 and version else "unknown"
            if code:
                return {**report, "status": "failed", "reason": "cli_version_failed", "network_invoked": False}
            if not live:
                return {**report, "status": "diagnosed", "network_invoked": False}
            report["network_invoked"] = True
            cid = None
            for name, prompt, fmt in (
                ("hello", "こんにちは。日本語で返答してください。", "json"),
                ("readme", "現在のフォルダのREADME.mdを読み、識別子READ_EVIDENCE_4f99だけを返してください。書き込み・削除・コマンド実行・補助Agent起動はしないでください。", "stream-json"),
                ("continue", "前の会話で確認したREADMEの識別子を答えてください。", "json"),
            ):
                # Plan mode exposes read-only investigation tools; the terminal
                # sandbox adds OS restrictions. Never grant permissions to tools.
                command = [binary, "-p", prompt, "--mode=plan", "--sandbox", "--output-format", fmt]
                # Explicit ID only; never --continue (which could mix threads).
                if cid:
                    command += ["--conversation", cid]
                code, output, diagnostic = invoke(command, root)
                parser = Protocol(cid)
                tools = []
                try:
                    for line in output.splitlines():
                        if line.strip():
                            event = parser.feed(line)
                            if "tool" in event:
                                tools.append({"name": event["tool"], "state": event["state"]})
                    result = parser.finish()
                except ValueError:
                    report["checks"].append({"name": name, "status": "failed", "reason": error_category(diagnostic)})
                    break
                cid = result["conversation_id"]
                observed_names = {tool["name"] for tool in tools}
                unsafe_tools = observed_names - {"read_file", "search_files", "list_directory"}
                read_evidence = "READ_EVIDENCE_4f99" in result["response"]
                safe_read = name != "readme" or ("read_file" in observed_names and read_evidence and not unsafe_tools)
                passed = code == 0 and result["status"] == "SUCCESS" and safe_read and not unsafe_tools
                report["checks"].append({"name": name, "status": "passed" if passed else "failed",
                                         "conversation_id": cid, "usage": result["usage"], "error": result["error"],
                                         "tools_observed": tools, "fixture_marker_in_response": read_evidence,
                                         "read_only_mode": "plan_and_sandbox", "unsafe_tool_observed": bool(unsafe_tools)})
                if not passed:
                    break
            report["authentication"] = "official_cli_managed_unknown_account_type"
            report["status"] = "completed" if len(report["checks"]) == 3 and all(x["status"] == "passed" for x in report["checks"]) else "failed"
            return report
        except (OSError, ValueError, TimeoutError, InterruptedError) as error:
            return {**report, "status": "failed", "reason": "timeout" if isinstance(error, TimeoutError) else "cancelled" if isinstance(error, InterruptedError) else "probe_error"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Run direct official CLI with synthetic prompts; never enables PETIT integration")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = run(live=args.live)
    rendered = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered)
    return 1 if report["status"] == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
