import base64
import json
import os
import signal
import struct
import subprocess
import sys
import threading
import urllib.request
from datetime import datetime
from pathlib import Path

# ── Config ────────────────────────────────────────────────────────────────────

def load_env():
    env = Path.cwd() / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val

load_env()

API_KEY  = os.environ.get("GEMINI_API_KEY", "")
MIC      = os.environ.get("MIC_DEVICE", "default")
SPEAKER  = os.environ.get("SPEAKER_DEVICE", "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor")
CALLS_DIR = Path.home() / "Documents" / "calls"

SAMPLE_RATE = 16000
CHUNK_MS    = 5000
CHUNK_BYTES = SAMPLE_RATE * 2 * CHUNK_MS // 1000  # s16le mono

GEMINI_URL = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={API_KEY}"

# ── WAV ───────────────────────────────────────────────────────────────────────

def to_wav(pcm: bytes) -> bytes:
    n = len(pcm)
    header = struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF", 36 + n, b"WAVE",
        b"fmt ", 16, 1, 1,
        SAMPLE_RATE, SAMPLE_RATE * 2, 2, 16,
        b"data", n,
    )
    return header + pcm

# ── Gemini ────────────────────────────────────────────────────────────────────

def transcribe(pcm: bytes, ts: str):
    body = json.dumps({
        "contents": [{"parts": [
            {"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(to_wav(pcm)).decode()}},
            {"text": "Transcribe the speech exactly as spoken. Output only the spoken words. If silence, output nothing."},
        ]}],
        "generationConfig": {"temperature": 0},
    }).encode()

    req = urllib.request.Request(
        GEMINI_URL,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read())
                text = (
                    data.get("candidates", [{}])[0]
                        .get("content", {})
                        .get("parts", [{}])[0]
                        .get("text", "")
                        .strip()
                )
                if text and any(c.isalpha() for c in text):
                    print(f"[{ts}] {text}", flush=True)
                return
        except Exception as e:
            if attempt == 1:
                print(f"API error: {e}", file=sys.stderr, flush=True)

# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    if not API_KEY:
        sys.exit("Missing GEMINI_API_KEY in .env")

    input("Use HEADSET to avoid echo. ENTER starts, Ctrl+C cancels: ")

    CALLS_DIR.mkdir(parents=True, exist_ok=True)
    out = CALLS_DIR / f"record-{datetime.now().strftime('%Y-%m-%d-%H-%M-%S')}.opus"

    print(f"\nRecording → {out}")
    print("Transcribing live… (Ctrl+C to stop)\n")

    # Single FFmpeg process: two outputs
    #   [rec] → archival Opus file (Anand's format)
    #   [pcm] → raw PCM pipe for transcription
    ffmpeg = subprocess.Popen(
        [
            "ffmpeg",
            "-hide_banner", "-loglevel", "error",
            "-f", "pulse", "-i", MIC,
            "-f", "pulse", "-i", SPEAKER,
            "-filter_complex",
                "[0:a]highpass=f=100,lowpass=f=12000,afftdn=nf=-30,volume=2[m];"
                "[1:a]pan=mono|c0=FR[s];"
                "[m]asplit=2[m1][m2];"
                "[s]asplit=2[s1][s2];"
                "[m1][s1]amerge,loudnorm=I=-16:LRA=7:tp=-1[rec];"
                "[m2][s2]amix=inputs=2:weights=1 1:normalize=0,"
                "aresample=16000,aformat=sample_fmts=s16:channel_layouts=mono,asetpts=N/SR/TB[pcm]",
            # Output 1: archival recording
            "-map", "[rec]", "-ar", "48000", "-ac", "2",
            "-c:a", "libopus", "-b:a", "24k", str(out),
            # Output 2: raw PCM for transcription
            "-map", "[pcm]", "-f", "s16le", "-acodec", "pcm_s16le",
            "-ac", "1", "-ar", "16000", "pipe:1",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        stdin=subprocess.DEVNULL,
    )

    threading.Thread(
        target=lambda: [
            print(f"[ffmpeg] {line.decode().strip()}", file=sys.stderr)
            for line in ffmpeg.stderr if line.strip()
        ],
        daemon=True,
    ).start()

    def handle_signal(*_):
        ffmpeg.terminate()
        print(f"\nSaved → {out}")
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_signal)
    signal.signal(signal.SIGTERM, handle_signal)

    buf = b""
    while chunk := ffmpeg.stdout.read(4096):
        buf += chunk
        while len(buf) >= CHUNK_BYTES:
            ts = datetime.now().strftime("%H:%M:%S")
            threading.Thread(target=transcribe, args=(buf[:CHUNK_BYTES], ts), daemon=True).start()
            buf = buf[CHUNK_BYTES:]

    if ffmpeg.returncode not in (0, -signal.SIGTERM, None):
        sys.exit(f"ffmpeg exited (code={ffmpeg.returncode})")


if __name__ == "__main__":
    main()
