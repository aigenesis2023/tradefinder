"""
LLM client — wraps the `claude` CLI available in Claude Code.

Uses the active Claude Code subscription. No API key required.
Call with: call_claude(prompt) -> str | None
"""

import subprocess
import shutil


def call_claude(prompt: str, timeout: int = 120) -> str | None:
    """
    Call Claude via the claude CLI subprocess.
    Returns the response text, or None on failure.
    """
    claude_bin = shutil.which("claude")
    if not claude_bin:
        print("[LLM] ERROR: 'claude' CLI not found in PATH. Is Claude Code installed?")
        return None
    try:
        result = subprocess.run(
            [claude_bin, "--print", prompt],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode != 0:
            print(f"[LLM] claude CLI returned non-zero: {result.stderr[:300]}")
            return None
        return result.stdout.strip() or None
    except subprocess.TimeoutExpired:
        print(f"[LLM] claude CLI timed out after {timeout}s")
        return None
    except Exception as e:
        print(f"[LLM] claude CLI exception: {e}")
        return None
