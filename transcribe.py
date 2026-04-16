import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

LAG_SECONDS = 2
POLL_INTERVAL = 1
WORKERS = 4
STABLE_EXIT_SECONDS = 10
SILENCE = {"silence", "no speech", "no spoken words", "no audio", "inaudible", ""}


def load_env():
    env = Path.cwd() / ".env"
    if not env.exists():
        return
    for line in env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k, v = k.strip(), v.strip().strip('"').strip("'")
        if k and k not in os.environ:
            os.environ[k] = v


load_env()


def parse_args():
    p = argparse.ArgumentParser(
        description="Follow a growing .opus file and print real-time Gemini transcripts."
    )
    p.add_argument("-i", "--input", required=True, help="Path to the .opus file being written by ffmpeg.")
    p.add_argument("-o", "--output-dir", default=os.environ.get("TRANSCRIPT_DIR", str(Path.home() / "Documents" / "transcripts")), help="Directory for saved transcripts.")
    p.add_argument("--no-save", action="store_true", help="Print only; don't save to disk.")
    p.add_argument("--chunk-seconds", type=float, default=float(os.environ.get("CHUNK_SECONDS", "5")), help="Seconds per chunk (default: 5).")
    p.add_argument("--from-start", action="store_true", help="Transcribe from the beginning instead of jumping to live position.")
    p.add_argument("--exit-after", type=float, default=STABLE_EXIT_SECONDS, help=f"Exit after file stops growing for N seconds (default: {STABLE_EXIT_SECONDS}). Set to 0 to never exit.")
    p.add_argument("--model", default=os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"), help="Gemini model (default: gemini-2.5-flash).")
    return p.parse_args()


def require(name):
    if not shutil.which(name):
        sys.exit(f"Missing required binary: {name}")


def api_url(model):
    key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not key:
        sys.exit("Set GEMINI_API_KEY in your environment or .env file")
    base = os.environ.get("GEMINI_API_BASE", "https://generativelanguage.googleapis.com").rstrip("/")
    return f"{base}/v1beta/models/{model}:generateContent?key={key}"


def probe_duration(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=False,
    )
    try:
        d = float(r.stdout.strip())
        return max(d, 0.0)
    except (ValueError, AttributeError):
        return None


def extract_wav(path, start, duration):
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-hide_banner", "-loglevel", "error",
         "-ss", f"{start:.3f}", "-t", f"{duration:.3f}", "-i", str(path),
         "-vn", "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"],
        capture_output=True, check=False,
    )
    return r.stdout if r.returncode == 0 and len(r.stdout) > 44 else None


def transcribe(wav_bytes, url):
    prompt = (
        "Transcribe ALL spoken words exactly as heard. Include filler words and partial words. "
        "Return ONLY the transcript. If no speech, return exactly: [silence]"
    )
    body = json.dumps({
        "contents": [{"parts": [
            {"inlineData": {"mimeType": "audio/wav", "data": base64.b64encode(wav_bytes).decode()}},
            {"text": prompt},
        ]}],
        "generationConfig": {"temperature": 0},
    }).encode()

    for attempt in range(3):
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
                for c in data.get("candidates", []):
                    texts = [p.get("text", "") for p in c.get("content", {}).get("parts", []) if p.get("text")]
                    result = "".join(texts).strip()
                    if result:
                        return result
                return ""
        except Exception as e:
            if attempt == 2:
                print(f"API error: {e}", file=sys.stderr, flush=True)
            time.sleep(min(2 ** attempt, 5))
    return ""


def is_silence(text):
    if not text:
        return True
    cleaned = text.lower().strip("[]() .\n")
    return cleaned in SILENCE or cleaned.startswith("no spoken")


def fmt(seconds):
    s = max(int(seconds), 0)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def span(start, end):
    return f"{fmt(start)}-{fmt(end)}"


def process_chunk(path, start, duration, url):
    wav = extract_wav(path, start, duration)
    if wav is None:
        return (start, start + duration, "")
    return (start, start + duration, transcribe(wav, url).strip())


def file_is_growing(path, wait=2.0):
    try:
        s1 = path.stat().st_size
    except FileNotFoundError:
        return False
    time.sleep(wait)
    try:
        return path.stat().st_size > s1
    except FileNotFoundError:
        return False


def main():
    args = parse_args()
    require("ffmpeg")
    require("ffprobe")

    input_path = Path(args.input).expanduser()
    url = api_url(args.model)
    output_dir = Path(args.output_dir).expanduser()

    # Transcript file setup
    transcript_file = None
    state_path = None
    if not args.no_save:
        output_dir.mkdir(parents=True, exist_ok=True)
        stem = input_path.stem
        transcript_file = output_dir / f"{stem}_{datetime.now().strftime('%Y%m%d')}.txt"
        state_path = output_dir / f".{stem}.state.json"
        if not transcript_file.exists():
            transcript_file.write_text(f"# Transcript of {input_path.name}\n# Started: {datetime.now().isoformat()}\n\n")
        print(f"Saving to: {transcript_file}", flush=True)

    # Determine starting position
    next_start = 0.0
    if not args.from_start and state_path and state_path.exists():
        try:
            next_start = float(json.loads(state_path.read_text()).get("next_start", 0))
            if next_start > 0:
                print(f"Resuming from {fmt(next_start)}", flush=True)
        except (json.JSONDecodeError, ValueError):
            next_start = 0.0

    # Wait for file and detect live position
    if not args.from_start and next_start == 0.0:
        while not input_path.exists():
            print(f"Waiting for: {input_path}", flush=True)
            time.sleep(POLL_INTERVAL)
        growing = file_is_growing(input_path)
        dur = probe_duration(input_path)
        if dur and dur > args.chunk_seconds and growing:
            next_start = max(0.0, dur - LAG_SECONDS)
            print(f"Live: jumping to {fmt(next_start)} ({dur:.0f}s file)", flush=True)

    print(f"Following: {input_path} | chunk={args.chunk_seconds:g}s", flush=True)

    max_dur = 0.0
    last_size = None
    last_change = time.monotonic()
    in_flight: deque[tuple[float, float, Future]] = deque()

    def drain():
        while in_flight:
            s, e, fut = in_flight[0]
            if not fut.done():
                break
            in_flight.popleft()
            try:
                _, _, text = fut.result()
            except Exception:
                continue
            if not is_silence(text):
                line = f"[{span(s, e)}] {text}"
                print(line, flush=True)
                if transcript_file:
                    with open(transcript_file, "a") as f:
                        f.write(line + "\n")
            if state_path:
                state_path.write_text(json.dumps({"next_start": e}))

    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        while True:
            if not input_path.exists():
                drain()
                time.sleep(POLL_INTERVAL)
                continue

            try:
                size = input_path.stat().st_size
            except FileNotFoundError:
                drain()
                time.sleep(POLL_INTERVAL)
                continue

            if last_size is None or size != last_size:
                last_size = size
                last_change = time.monotonic()

            dur = probe_duration(input_path)
            if dur is not None:
                max_dur = max(max_dur, dur)

            stable = args.exit_after > 0 and (time.monotonic() - last_change) >= args.exit_after
            ready = max_dur if stable else max(0.0, max_dur - LAG_SECONDS)

            # Dispatch chunks
            dispatched = False
            while next_start + args.chunk_seconds <= ready + 1e-6 and len(in_flight) < WORKERS * 2:
                fut = pool.submit(process_chunk, input_path, next_start, args.chunk_seconds, url)
                in_flight.append((next_start, next_start + args.chunk_seconds, fut))
                next_start += args.chunk_seconds
                dispatched = True

            # Partial chunk for lower latency
            if not dispatched and not stable and not in_flight:
                partial = ready - next_start
                if partial >= 2.0:
                    fut = pool.submit(process_chunk, input_path, next_start, partial, url)
                    in_flight.append((next_start, next_start + partial, fut))
                    next_start += partial
                    dispatched = True

            drain()

            if stable:
                for s, e, fut in in_flight:
                    try:
                        _, _, text = fut.result(timeout=60)
                        if not is_silence(text):
                            line = f"[{span(s, e)}] {text}"
                            print(line, flush=True)
                            if transcript_file:
                                with open(transcript_file, "a") as f:
                                    f.write(line + "\n")
                    except Exception:
                        pass
                in_flight.clear()
                remaining = max_dur - next_start
                if remaining > 0.25:
                    _, _, text = process_chunk(input_path, next_start, remaining, url)
                    if not is_silence(text):
                        line = f"[{span(next_start, next_start + remaining)}] {text}"
                        print(line, flush=True)
                        if transcript_file:
                            with open(transcript_file, "a") as f:
                                f.write(line + "\n")
                print("Done — file stopped growing.", flush=True)
                return 0

            time.sleep(POLL_INTERVAL if not dispatched and not in_flight else 0.2)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
        raise SystemExit(130)
