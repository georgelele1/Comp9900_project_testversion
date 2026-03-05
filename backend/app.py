from __future__ import annotations
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, Callable
from connectonion.address import load
from connectonion import Agent, host, transcribe

APP_NAME = "Whispr"

# -------------------------
# Local storage (optional, for future snippets/history)
# -------------------------
def app_support_dir() -> Path:
    home = Path.home()
    if sys.platform == "darwin":
        base = home / "Library" / "Application Support" / APP_NAME
    elif os.name == "nt":
        base = Path(os.environ.get("APPDATA", str(home))) / APP_NAME
    else:
        base = home / ".local" / "share" / APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base

def now_ms() -> int:
    return int(time.time() * 1000)

# -------------------------
# Tool registration helper (works across CO versions)
# -------------------------
def register_tool(agent: Agent, fn: Callable[..., Any]) -> None:
    # Newer builds
    if hasattr(agent, "add_tools") and callable(getattr(agent, "add_tools")):
        agent.add_tools(fn)
        return
    if hasattr(agent, "add_tool") and callable(getattr(agent, "add_tool")):
        agent.add_tool(fn)
        return

    # Older builds: ToolRegistry on agent.tools
    reg = getattr(agent, "tools", None)
    if reg is not None:
        for meth in ("register", "add", "add_tool", "add_function", "append"):
            m = getattr(reg, meth, None)
            if callable(m):
                m(fn)
                return

    raise RuntimeError("Cannot register tool: unknown connectonion tool API in this install.")

# -------------------------
# Agent factory
# -------------------------
def create_agent() -> Agent:
    # MAIN ORCHESTRATOR AGENT
    agent = Agent(
        model="co/gpt-5",  # Note: If 500 errors persist after this fix, try co/gpt-4o
        name="whispr_orchestrator",
        system_prompt=(
            "You are Whispr. You orchestrate audio transcriptions and enhancements.\n"
            "When asked to transcribe and enhance audio, use the transcribe_and_enhance tool."
        ),
    )

    def transcribe_and_enhance(
        audio_path: str,
        mode: str = "clean",        # off | clean | formal
        context: str = "generic",   # generic | email | chat | code
        prompt: str = "",           # STT prompt (domain terms)
    ) -> Dict[str, Any]:
        """
        1) transcribe(audio_path)
        2) enhance using a DEDICATED Sub-Agent LLM (unless mode == 'off')
        """
        # Normalize inputs (avoid weird values from UI)
        mode = (mode or "clean").strip().lower()
        context = (context or "generic").strip().lower()

        if mode not in {"off", "clean", "formal"}:
            mode = "clean"
        if context not in {"generic", "email", "chat", "code"}:
            context = "generic"

        # --- Speech to text ---
        if prompt.strip():
            raw = transcribe(audio_path, prompt=prompt.strip())
        else:
            raw = transcribe(audio_path)

        raw_text = str(raw).strip()

        # --- Enhancement ---
        if mode == "off":
            final_text = raw_text
        else:
            instruction = f"""
Context: {context}
Enhancement level: {mode}

Transcript:
{raw_text}
""".strip()

            # IMPORTANT FIX: DEDICATED SUB-AGENT
            # This prevents the recursion bug by using a fresh session state.
            enhancer_agent = Agent(
                model="co/gpt-5", 
                name="whispr_enhancer",
                system_prompt=(
                    "You are Whispr. Improve the transcript.\n"
                    "Rules:\n"
                    "- Do NOT add new facts.\n"
                    "- Do NOT change meaning.\n"
                    "- Fix punctuation, capitalization, and grammar.\n"
                    "- Remove filler words (um/uh/like/you know), stutters, and repeated fragments.\n"
                    "- Resolve false starts and self-corrections (keep only the corrected version).\n"
                    "- Output ONLY the final improved text. No quotes. No commentary."
                )
            )

            final_text = str(enhancer_agent.input(instruction)).strip()

            # Small cleanup in case the model still wraps output in quotes
            final_text = final_text.strip().strip('"').strip("'").strip()

        return {"ok": True, "raw_text": raw_text, "final_text": final_text, "ts": now_ms()}

    register_tool(agent, transcribe_and_enhance)
    return agent


if __name__ == "__main__":
    # Load the exact same credentials that your test script uses
    addr = load(Path(".co"))
    my_agent_address = addr["address"]

    host(
        create_agent,
        relay_url=None,
        whitelist=[my_agent_address],  # Explicitly allow your testcall's address
        blacklist=[],
    )