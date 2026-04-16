# livetrans

Real-time transcription of a growing `.opus` recording using the Gemini API.

One terminal records, another transcribes — text appears within seconds of speaking.

---

## Requirements

- **Linux** with PulseAudio / PipeWire
- **FFmpeg + FFprobe**: `sudo apt install ffmpeg`
- **uv**: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- A **Gemini API key** from [aistudio.google.com](https://aistudio.google.com/)

---

## Quick Start

Open two terminals side by side.

### Terminal 1 — Record

```bash
mkdir -p ~/Documents/calls

ffmpeg -hide_banner -stats -v error \
  -f pulse -i default \
  -c:a libopus -b:a 24k \
  ~/Documents/calls/call.opus
```

This starts recording your microphone to an `.opus` file. Press `Ctrl+C` to stop.

<details>
<summary>Record microphone + system audio (both sides of a call)</summary>

First, find your speaker monitor source:

```bash
pactl list short sources | grep monitor
```

Then use it as the second input:

```bash
ffmpeg -hide_banner -stats -v error \
  -f pulse -i default \
  -f pulse -i <your-monitor-source-name> \
  -filter_complex "\
    [0:a]highpass=f=100,lowpass=f=12000,afftdn=nf=-30,volume=2[m]; \
    [1:a]pan=mono|c0=FR[s]; \
    [m][s]amerge,loudnorm=I=-16:LRA=7:tp=-1[a]" \
  -map "[a]" \
  -ar 48000 -ac 2 -c:a libopus -b:a 24k \
  ~/Documents/calls/call.opus
```
</details>

### Terminal 2 — Transcribe

No cloning needed — run directly with `uvx`:

```bash
GEMINI_API_KEY=your_key \
  uvx --from git+https://github.com/Ritesh17rb/ffmpeg-transcriber \
  transcribe -i ~/Documents/calls/call.opus
```

The transcriber will detect the growing file, jump to the live position, and start printing transcriptions as you speak.

---

## Local Development

```bash
git clone https://github.com/Ritesh17rb/ffmpeg-transcriber
cd ffmpeg-transcriber

echo 'GEMINI_API_KEY=your_key' > .env

uv run transcribe -i ~/Documents/calls/call.opus
```

---

## What Happens

1. **Terminal 1** — ffmpeg writes audio to a growing `.opus` file.
2. **Terminal 2** — the transcriber detects the file is growing and jumps to the live position.
3. Every 5s of audio is chunked, sent to Gemini in parallel (4 workers), and printed in order.
4. Silence is filtered out — only speech lines are printed and saved.
5. Transcripts are saved to `~/Documents/transcripts/<name>_<date>.txt`.
6. The transcriber stays open, polling for new audio — it never exits until you `Ctrl+C`.
7. If you restart, it resumes from where it left off.

---

## CLI Reference

```
transcribe -i <file> [options]
```

| Flag | Default | Description |
|---|---|---|
| `-i`, `--input` | *(required)* | Path to the audio file being written |
| `-o`, `--output-dir` | `~/Documents/transcripts` | Where to save transcripts |
| `--no-save` | off | Print to terminal only, don't save files |
| `--chunk-seconds` | `5` | Audio chunk size per API call |
| `--from-start` | off | Transcribe from the beginning instead of live position |
| `--exit-after` | `0` | Exit after file stops growing for N seconds (0 = never) |
| `--model` | `gemini-2.5-flash` | Gemini model to use |

## Environment Variables

Set in `.env` or export in your shell:

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | *(required)* Google AI API key |
| `GEMINI_MODEL` | Model override (default: `gemini-2.5-flash`) |
| `CHUNK_SECONDS` | Default chunk size |
| `TRANSCRIPT_DIR` | Default save directory |
