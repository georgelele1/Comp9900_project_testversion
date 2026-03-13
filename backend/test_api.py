"""
test the server endpoints. start server first:
    python server.py --mock
then:
    python test_api.py
"""

import os, sys, tempfile
import requests

URL = "http://127.0.0.1:5055"


def tmp_audio(ext=".wav", size=1024):
    """make a dummy file - doesn't need to be real audio for mock mode"""
    p = os.path.join(tempfile.gettempdir(), f"test{ext}")
    with open(p, "wb") as f:
        f.write(b"\x00" * size)
    return p


# -------------------------------------------------

print("checking health...")
try:
    r = requests.get(f"{URL}/health", timeout=5)
    assert r.status_code == 200, f"health check failed: {r.status_code}"
    print(f"  server ok (mock={r.json().get('mock')})")
except requests.ConnectionError:
    print("  server not running! do: python server.py --mock")
    sys.exit(1)


# basic upload - should get transcribed text back
print("\ntest: basic upload...")
with open(tmp_audio(".wav"), "rb") as f:
    r = requests.post(f"{URL}/transcribe",
        files={"file": ("whispr_recording.wav", f, "audio/wav")},
        data={"mode": "clean"}, timeout=30)
d = r.json()
assert r.status_code == 200, f"expected 200, got {r.status_code}"
assert d.get("text"), "no text in response"
assert d.get("error") is None, f"unexpected error: {d.get('error')}"
print(f"  ok: \"{d['text'][:50]}...\"")


# formal mode
print("\ntest: formal mode...")
with open(tmp_audio(".m4a"), "rb") as f:
    r = requests.post(f"{URL}/transcribe",
        files={"file": ("recording.m4a", f, "audio/mp4")},
        data={"mode": "formal", "context": "email"}, timeout=30)
d = r.json()
assert r.status_code == 200
assert d.get("meta", {}).get("mode") == "formal", f"meta wrong: {d.get('meta')}"
print(f"  ok: \"{d['text'][:50]}\"")


# request id should come back
print("\ntest: request_id...")
with open(tmp_audio(), "rb") as f:
    r = requests.post(f"{URL}/transcribe",
        files={"file": ("test.wav", f)},
        data={"request_id": "abc-123"}, timeout=30)
assert r.json().get("request_id") == "abc-123", "id not echoed"
print("  ok")


# no file -> should reject
print("\ntest: no file...")
r = requests.post(f"{URL}/transcribe", data={"mode": "clean"}, timeout=10)
assert r.status_code in (400, 422), f"should reject, got {r.status_code}"
print(f"  ok: rejected with {r.status_code}")


# wrong extension
print("\ntest: bad extension...")
with open(tmp_audio(".txt"), "rb") as f:
    r = requests.post(f"{URL}/transcribe",
        files={"file": ("notes.txt", f)}, timeout=10)
assert r.status_code == 400, f"should be 400, got {r.status_code}"
assert r.json().get("error", {}).get("code") == "INVALID_FORMAT"
print("  ok: rejected txt")


# empty file
print("\ntest: empty file...")
with open(tmp_audio(".wav", size=50), "rb") as f:
    r = requests.post(f"{URL}/transcribe",
        files={"file": ("x.wav", f)}, timeout=10)
assert r.status_code == 400
assert r.json().get("error", {}).get("code") == "EMPTY_AUDIO"
print("  ok: rejected empty")


# mode=off should give raw text
print("\ntest: mode off...")
with open(tmp_audio(), "rb") as f:
    r = requests.post(f"{URL}/transcribe",
        files={"file": ("t.wav", f)},
        data={"mode": "off"}, timeout=30)
d = r.json()
assert r.status_code == 200 and d.get("text")
print(f"  ok: \"{d['text'][:50]}\"")


print("\n---")
print("all tests passed")
