"""
agents/intent.py — LLM-based intent detection.

Single LLM call classifies intent into: calendar | knowledge | refine

No regex Layer 1 — the LLM handles all cases including edge cases like
"what is my exam date" (calendar) vs "what is Newton's law" (knowledge).

Followup detection uses shared session context so consecutive questions
route correctly based on previous exchange type.
"""
from __future__ import annotations

import sys
import io as _io
from storage import get_agent_model
_real = sys.stdout
sys.stdout = _io.StringIO()
from connectonion import Agent
sys.stdout = _real


def _classify(text: str, session_context: str = "") -> str:
    session_hint = f"\n\nRecent conversation:\n{session_context}" if session_context else ""

    agent = Agent(
        model=get_agent_model(),
        name="whispr_intent_classifier",
        system_prompt=(
            "You classify voice transcriptions for a voice assistant.\n\n"
            "STEP 1 — Analyse the sentence structure:\n"
            "  - Is it a question or a retrieval request? (yes/no)\n"
            "  - What is the subject — personal schedule/events, world knowledge, or text to dictate?\n"
            "  - Is there an explicit intent to look something up, or is the user stating/dictating?\n\n"
            "STEP 2 — Apply these rules in order:\n"
            "  calendar  → question/retrieval AND subject is the user's own schedule, events, "
            "appointments, or time slots. Both must be true.\n"
            "  knowledge → question or request for factual/conceptual information about the world "
            "that does not depend on the user's personal data.\n"
            "  refine    → everything else: statements, dictation, messages, names, notes, "
            "short phrases, or anything where intent is unclear. This is the default.\n\n"
            "STEP 3 — Output only the label.\n\n"
            "Use recent conversation to resolve ambiguous continuations.\n"
            f"{session_hint}\n\n"
            "Reply ONLY with one word: calendar, knowledge, or refine."
        ),
    )
    result = str(agent.input(text)).strip().lower()
    return result if result in ("calendar", "knowledge", "refine") else "refine"


def detect_intent(text: str) -> str:
    """Returns: 'calendar' | 'knowledge' | 'refine'"""
    from agents.plugins.session import get_session_context, is_followup, _load

    # Fast-path for obvious followups — check session to decide which agent
    session = _load()
    if is_followup(text) and session:
        for msg in reversed(session):
            if msg["role"] == "assistant":
                content = msg["content"]
                # If previous answer looks like knowledge, continue with knowledge
                if len(content) > 100 or any(
                    kw in content.lower() for kw in
                    ["formula", "equation", "defined as", "refers to", "is a type",
                     "algorithm", "protocol", "theorem", "law of", "concept"]
                ):
                    print("[intent] followup → knowledge", file=sys.stderr)
                    return "knowledge"
                print("[intent] followup → refine", file=sys.stderr)
                return "refine"

    intent = _classify(text, get_session_context())
    print(f"[intent] LLM → {intent}", file=sys.stderr)
    return intent