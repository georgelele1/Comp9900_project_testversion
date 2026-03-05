from __future__ import annotations

import os
import sys
import time
import uuid
import base64
from pathlib import Path
from typing import Any, Dict, Callable

from fastapi import FastAPI, UploadFile, File
from fastapi.responses import JSONResponse
import uvicorn

from connectonion.address import load
from connectonion import Agent, host, transcribe


APP_NAME = "Whispr"

app = FastAPI()


# -------------------------
# Local storage
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
# Tool registration helper
# -------------------------
def register_tool(agent: Agent, fn: Callable[..., Any]) -> None:

    if hasattr(agent, "add_tools"):
        agent.add_tools(fn)
        return

    if hasattr(agent, "add_tool"):
        agent.add_tool(fn)
        return

    reg = getattr(agent, "tools", None)

    if reg:
        for m in ("register", "add", "add_tool", "append"):
            f = getattr(reg, m, None)
            if callable(f):
                f(fn)
                return

    raise RuntimeError("Cannot register tool.")


# -------------------------
# Agent
# -------------------------
def create_agent() -> Agent:

    agent = Agent(
        model="co/gpt-5",
        name="whispr_orchestrator",
        system_prompt=(
            "You are Whispr. "
            "Transcribe audio and enhance transcripts."
        ),
    )

    def transcribe_and_enhance(
        audio_path: str,
        mode: str = "clean",
        context: str = "generic",
        prompt: str = "",
    ) -> Dict[str, Any]:

        if prompt.strip():
            raw = transcribe(audio_path, prompt=prompt)
        else:
            raw = transcribe(audio_path)

        raw_text = str(raw).strip()

        if mode == "off":
            final_text = raw_text

        else:

            enhancer = Agent(
                model="co/gpt-5",
                name="whispr_enhancer",
                system_prompt=(
                    "Improve transcript grammar and clarity. "
                    "Do not add new facts."
                ),
            )

            instruction = f"""
Context: {context}

Transcript:
{raw_text}
"""

            final_text = str(enhancer.input(instruction)).strip()

        return {
            "ok": True,
            "raw_text": raw_text,
            "final_text": final_text,
            "ts": now_ms(),
        }

    register_tool(agent, transcribe_and_enhance)

    return agent


# Create the agent once
agent = create_agent()


# -------------------------
# HTTP Upload Endpoint
# -------------------------
@app.post("/transcribe")
async def transcribe_upload(file: UploadFile = File(...)):
    audio_bytes = await file.read()

    save_dir = app_support_dir() / "recordings"
    save_dir.mkdir(parents=True, exist_ok=True)

    # preserve original extension if possible
    filename = (file.filename or "").lower()
    ext = "m4a"
    if "." in filename:
        ext = filename.rsplit(".", 1)[1] or "m4a"

    audio_path = save_dir / f"{uuid.uuid4().hex}.{ext}"
    audio_path.write_bytes(audio_bytes)

    try:
        result = agent.tools.transcribe_and_enhance(
            audio_path=str(audio_path),
            mode="clean",
            context="generic",
            prompt=""
        )
        return JSONResponse({"text": result["final_text"]})

    except Exception as e:
        # return the connectonion error to the frontend for debugging
        return JSONResponse(
            status_code=500,
            content={
                "error": "transcribe_failed",
                "details": str(e),
                "saved_path": str(audio_path),
                "filename": file.filename,
                "content_type": file.content_type,
                "size_bytes": len(audio_bytes),
            },
        )


# -------------------------
# Main
# -------------------------
if __name__ == "__main__":

    # Load connectonion credentials
    addr = load(Path(".co"))
    my_agent_address = addr["address"]

    # Start ConnectOnion host in background
    import threading

    def start_agent():
        host(
            create_agent,
            relay_url=None,
            whitelist=[my_agent_address],
            blacklist=[],
        )

    threading.Thread(target=start_agent, daemon=True).start()

    # Start HTTP server
    uvicorn.run(app, host="127.0.0.1", port=5055)