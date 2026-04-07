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
from pathlib import Path


def load_env() -> None:
    env = Path.cwd() / ".env"
    if not env.exists():
        return
    for raw_line in env.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env()

DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash")
DEFAULT_CHUNK_SECONDS = float(os.environ.get("CHUNK_SECONDS", "5"))
DEFAULT_LAG_SECONDS = float(os.environ.get("LAG_SECONDS", "5"))
DEFAULT_POLL_INTERVAL = float(os.environ.get("POLL_INTERVAL", "1"))
DEFAULT_EXIT_WHEN_STABLE = float(os.environ.get("EXIT_WHEN_STABLE", "15"))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Follow a growing .opus file and print Gemini transcripts in near real time."
    )
    parser.add_argument(
        "-i",
        "--input",
        required=True,
        help="Path to the .opus file being written by ffmpeg.",
    )
    parser.add_argument(
        "--chunk-seconds",
        type=float,
        default=DEFAULT_CHUNK_SECONDS,
        help="Chunk size sent for transcription. Default: 5 seconds.",
    )
    parser.add_argument(
        "--lag-seconds",
        type=float,
        default=DEFAULT_LAG_SECONDS,
        help="How far behind the writer to stay while following the file. Default: 5 seconds.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        help="How often to poll the input file for growth. Default: 1 second.",
    )
    parser.add_argument(
        "--exit-when-stable",
        type=float,
        default=DEFAULT_EXIT_WHEN_STABLE,
        help=(
            "Exit after the file stops growing for this many seconds. "
            "Set to 0 to follow forever."
        ),
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Gemini model to call. Default: {DEFAULT_MODEL}.",
    )
    return parser.parse_args()


def require_binary(name: str) -> None:
    if shutil.which(name):
        return
    sys.exit(f"Missing required binary: {name}")


def gemini_url(model: str) -> str:
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        sys.exit("Missing GEMINI_API_KEY in .env")
    base = os.environ.get("GEMINI_API_BASE", "https://generativelanguage.googleapis.com").rstrip("/")
    return f"{base}/v1beta/models/{model}:generateContent?key={api_key}"


def probe_duration(path: Path) -> float | None:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None

    output = result.stdout.strip()
    if not output or output == "N/A":
        return None

    try:
        duration = float(output)
    except ValueError:
        return None

    return max(duration, 0.0)


def extract_wav_chunk(path: Path, start: float, duration: float) -> bytes | None:
    if duration <= 0:
        return None

    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{start:.3f}",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-f",
            "wav",
            "pipe:1",
        ],
        capture_output=True,
        check=False,
    )
    if result.returncode != 0 or len(result.stdout) <= 44:
        return None
    return result.stdout


def parse_gemini_text(payload: dict) -> str:
    for candidate in payload.get("candidates", []):
        content = candidate.get("content", {})
        texts = [part.get("text", "") for part in content.get("parts", []) if part.get("text")]
        merged = "".join(texts).strip()
        if merged:
            return merged
    return ""


def transcribe_chunk(wav_bytes: bytes, url: str) -> str:
    prompt = (
        "Transcribe the spoken audio exactly as heard. "
        "Return only the transcript text. If there is no speech, return an empty response."
    )
    body = json.dumps(
        {
            "contents": [
                {
                    "parts": [
                        {
                            "inlineData": {
                                "mimeType": "audio/wav",
                                "data": base64.b64encode(wav_bytes).decode("ascii"),
                            }
                        },
                        {"text": prompt},
                    ]
                }
            ],
            "generationConfig": {"temperature": 0},
        }
    ).encode("utf-8")

    for attempt in range(3):
        request = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                payload = json.loads(response.read().decode("utf-8"))
                return parse_gemini_text(payload)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if attempt == 2:
                print(f"Gemini API error ({exc.code}): {detail}", file=sys.stderr, flush=True)
        except Exception as exc:  # pragma: no cover - network/runtime guard
            if attempt == 2:
                print(f"Gemini API error: {exc}", file=sys.stderr, flush=True)
        time.sleep(min(2**attempt, 5))

    return ""


def format_offset(seconds: float) -> str:
    whole_seconds = max(int(seconds), 0)
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def format_span(start: float, end: float) -> str:
    return f"{format_offset(start)}-{format_offset(end)}"


def process_chunk(path: Path, start: float, duration: float, url: str) -> bool:
    wav_chunk = extract_wav_chunk(path, start, duration)
    if wav_chunk is None:
        return False

    text = transcribe_chunk(wav_chunk, url).strip()
    if text:
        print(f"[{format_span(start, start + duration)}] {text}", flush=True)
    return True


def main() -> int:
    args = parse_args()
    if args.chunk_seconds <= 0:
        sys.exit("--chunk-seconds must be greater than 0")
    if args.lag_seconds < 0:
        sys.exit("--lag-seconds must be 0 or greater")
    if args.poll_interval <= 0:
        sys.exit("--poll-interval must be greater than 0")
    if args.exit_when_stable < 0:
        sys.exit("--exit-when-stable must be 0 or greater")

    require_binary("ffmpeg")
    require_binary("ffprobe")

    input_path = Path(args.input).expanduser()
    url = gemini_url(args.model)

    print(f"Following: {input_path}", flush=True)
    print(
        f"chunk={args.chunk_seconds:g}s lag={args.lag_seconds:g}s poll={args.poll_interval:g}s",
        flush=True,
    )

    next_start = 0.0
    max_duration = 0.0
    last_size: int | None = None
    last_change_at = time.monotonic()
    waiting_for_file = False

    while True:
        if not input_path.exists():
            if not waiting_for_file:
                print(f"Waiting for file: {input_path}", flush=True)
                waiting_for_file = True
            time.sleep(args.poll_interval)
            continue

        waiting_for_file = False

        try:
            size = input_path.stat().st_size
        except FileNotFoundError:
            time.sleep(args.poll_interval)
            continue

        if last_size is None or size != last_size:
            last_size = size
            last_change_at = time.monotonic()

        duration = probe_duration(input_path)
        if duration is not None:
            max_duration = max(max_duration, duration)

        stable = args.exit_when_stable > 0 and (time.monotonic() - last_change_at) >= args.exit_when_stable
        ready_until = max_duration if stable else max(0.0, max_duration - args.lag_seconds)

        processed_any = False
        while (next_start + args.chunk_seconds) <= (ready_until + 1e-6):
            if not process_chunk(input_path, next_start, args.chunk_seconds, url):
                break
            next_start += args.chunk_seconds
            processed_any = True

        if stable:
            remaining = max_duration - next_start
            if remaining > 0.25:
                process_chunk(input_path, next_start, remaining, url)
            print("Input stopped growing; exiting.", flush=True)
            return 0

        if not processed_any:
            time.sleep(args.poll_interval)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\nStopped.", flush=True)
        raise SystemExit(130)
