"""
HTTP server for Whispr. Takes audio uploads from the Swift app
and runs them through the backend transcription pipeline.

python server.py          # real mode (needs connectonion)
python server.py --mock   # returns fake data for testing
"""

import argparse
import time
import uuid
import tempfile
import traceback
from pathlib import Path

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn


PORT = 5055  # matches ContentView.swift

app = FastAPI(title="Whispr", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

UPLOAD_DIR = Path(tempfile.gettempdir()) / "whispr_uploads"
MOCK = False



# can't do `from app import transcribe_and_enhance` because yanbo
# defined it inside create_agent() as a nested function. so we have
# to import the module and call the pipeline functions ourselves.
_app = None

def _init_backend():
    global _app
    try:
        import app as backend_module
        _app = backend_module
        print("loaded app.py")
        return True
    except ImportError as e:
        print(f"can't load app.py ({e}), using mock mode")
        return False


def do_transcribe(audio_path, mode, context, prompt):
    """Call the same pipeline that transcribe_and_enhance() does,
    but through module-level functions."""
    stt_prompt = _app.build_dictionary_prompt(prompt)
    raw = _app.transcribe(audio_path, prompt=stt_prompt) if stt_prompt else _app.transcribe(audio_path)
    raw_text = str(raw).strip()

    # update personal dictionary from recent transcriptions
    _app.auto_update_dictionary_from_recent_texts(raw_text)
    normalized = _app.apply_dictionary_corrections(raw_text)

    if mode == "off":
        final = normalized
        bt = normalized
    else:
        bt = _app.ai_backtrace_correct(normalized, context, mode)
        bt = _app.apply_dictionary_corrections(bt)
        final = _app.ai_enhance_text(bt, context, mode)
        final = _app.apply_dictionary_corrections(final)

    _app.append_history({
        "ts": _app.now_ms(), "audio_path": audio_path,
        "raw_text": raw_text, "normalized_text": normalized,
        "backtrace_text": bt, "final_text": final,
        "context": context, "mode": mode,
    })
    return {"ok": True, "raw_text": raw_text, "final_text": final}


def mock_transcribe(audio_path, mode, context, prompt):
    raw = "um hello this is a test recording uh for the whispr project"
    if mode == "off": return {"ok": True, "raw_text": raw, "final_text": raw}
    if mode == "formal": return {"ok": True, "raw_text": raw, "final_text": "Hello. This is a test recording for the Whispr project."}
    return {"ok": True, "raw_text": raw, "final_text": "Hello, this is a test recording for the Whispr project."}



@app.get("/health")
async def health():
    return {"status": "ok", "mock": MOCK}


@app.post("/transcribe")
async def transcribe(
    # swift sends this as "file" (ContentView.swift:78), not "audio"
    file: UploadFile = File(...),
    mode: str = Form("clean"),
    context: str = Form("generic"),
    language: str = Form("auto"),
    prompt: str = Form(""),
    request_id: str = Form(None),
):
    rid = request_id or str(uuid.uuid4())

    if not file or not file.filename:
        return JSONResponse(status_code=400, content={
            "request_id": rid, "text": None,
            "error": {"code": "MISSING_AUDIO", "message": "No audio file."}
        })

    # swift records m4a but uploads it as .wav (AudioRecorder.swift:14
    # vs ContentView.swift:78) - so we accept both and don't stress
    # about the extension too much
    ext = Path(file.filename).suffix.lower()
    if ext not in (".m4a", ".wav", ".mp3", ".ogg", ".flac", ".aac", ".webm"):
        return JSONResponse(status_code=400, content={
            "request_id": rid, "text": None,
            "error": {"code": "INVALID_FORMAT", "message": f"Can't handle {ext} files."}
        })

    # sanitize params
    if mode not in ("off", "clean", "formal"): mode = "clean"
    if context not in ("generic", "email", "chat", "code"): context = "generic"

    # save to temp so backend can read it as a file path
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    tmp = UPLOAD_DIR / f"whispr_{rid}{ext}"

    try:
        raw_bytes = await file.read()
    except Exception as e:
        return JSONResponse(status_code=500, content={
            "request_id": rid, "text": None,
            "error": {"code": "UPLOAD_FAILED", "message": str(e)}
        })

    if len(raw_bytes) < 100:
        return JSONResponse(status_code=400, content={
            "request_id": rid, "text": None,
            "error": {"code": "EMPTY_AUDIO", "message": "Audio file too small."}
        })

    tmp.write_bytes(raw_bytes)

    # run through the pipeline
    try:
        t0 = time.time()
        fn = mock_transcribe if MOCK else do_transcribe
        result = fn(str(tmp), mode, context, prompt)
        ms = int((time.time() - t0) * 1000)
        # print(f"transcribe done in {ms}ms")  # uncomment for debugging

        if not result.get("ok"):
            return JSONResponse(status_code=500, content={
                "request_id": rid, "text": None,
                "error": {"code": "TRANSCRIBE_FAILED", "message": "Backend error."}
            })

        return {
            "request_id": rid,
            "raw_text": result.get("raw_text", ""),
            "text": result.get("final_text", ""),
            "meta": {"mode": mode, "context": context, "language": language, "duration_ms": ms},
            "error": None,
        }
    except Exception as e:
        traceback.print_exc()
        return JSONResponse(status_code=500, content={
            "request_id": rid, "text": None,
            "error": {"code": "TRANSCRIBE_FAILED", "message": str(e)}
        })
    finally:
        # cleanup - dont care if this fails
        try: tmp.unlink(missing_ok=True)
        except: pass



if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args()

    MOCK = args.mock

    if not MOCK:
        if not _init_backend():
            MOCK = True
            print("falling back to mock mode")

    if MOCK:
        print("mock mode - fake transcriptions")

    print(f"http://127.0.0.1:{args.port}/docs")
    uvicorn.run(app, host="127.0.0.1", port=args.port, log_level="info")
