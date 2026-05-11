"""
LLM client — wraps the `claude` CLI available in Claude Code.

Uses the active Claude Code subscription. No API key required.
Call with: call_claude(prompt) -> str | None
"""

import subprocess
import shutil
import time


def _call_once(claude_bin: str, prompt: str, timeout: int) -> tuple[str | None, str]:
    """Single CLI invocation. Returns (output_or_None, failure_kind)."""
    try:
        result = subprocess.run(
            [claude_bin, "--print", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            return None, f"nonzero exit ({result.returncode}): {result.stderr[:200]}"
        out = result.stdout.strip()
        return (out, "") if out else (None, "empty stdout")
    except subprocess.TimeoutExpired:
        return None, f"timeout after {timeout}s"
    except Exception as e:
        return None, f"exception: {e}"


def call_claude(prompt: str, timeout: int = 120, retries: int = 1) -> str | None:
    """
    Call Claude via the claude CLI subprocess.
    One retry by default on transient failure (timeout / non-zero exit / empty stdout).
    Returns the response text, or None after all attempts fail.
    """
    claude_bin = shutil.which("claude")
    if not claude_bin:
        print("[LLM] ERROR: 'claude' CLI not found in PATH. Is Claude Code installed?")
        return None

    attempts = retries + 1
    for i in range(attempts):
        out, fail = _call_once(claude_bin, prompt, timeout)
        if out is not None:
            return out
        if i < attempts - 1:
            print(f"[LLM] attempt {i+1}/{attempts} failed ({fail}) — retrying")
            time.sleep(1.5)
        else:
            print(f"[LLM] attempt {i+1}/{attempts} failed ({fail}) — giving up")
    return None
