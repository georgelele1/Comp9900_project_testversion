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
            "Classify this voice transcription into exactly one label:\n\n"
            "  calendar  — anything about the user's own schedule, events, appointments,\n"
            "              exams, deadlines, meetings, or asking when something is.\n"
            "              Examples: 'what is my exam date', 'when is my dentist',\n"
            "              'do I have anything today', 'search my calendar for COMP9417'\n\n"
            "  knowledge — asking a factual question, wanting an explanation, definition,\n"
            "              formula, concept, or how something works.\n"
            "              Examples: 'what is Newton's law', 'explain TCP vs UDP',\n"
            "              'give me the formula for kinetic energy'\n\n"
            "  refine    — dictating text to clean up, format, translate, or send.\n"
            "              Also continuations of previous dictation.\n"
            "              Examples: 'send an email to the team', 'translate that to Chinese',\n"
            "              'and also mention the deadline'\n\n"
            "Use the recent conversation to resolve ambiguous continuations.\n"
            "If the previous response was a knowledge answer and this continues that topic,\n"
            "classify as knowledge. If it continues dictation, classify as refine."
            f"{session_hint}\n\n"
            "Reply ONLY with the label. No explanation."
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