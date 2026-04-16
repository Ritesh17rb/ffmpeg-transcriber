# ffmpeg-transcriber

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

### Terminal 1 — Record

```bash
mkdir -p ~/Documents/calls

ffmpeg -hide_banner -stats -v error \
  -f pulse -i default \
  -c:a libopus -b:a 24k \
  ~/Documents/calls/call.opus
```

<details>
<summary>Record microphone + system audio (both sides of a call)</summary>

```bash
ffmpeg -hide_banner -stats -v error \
  -f pulse -i default \
  -f pulse -i $(pactl list short sources | grep monitor | head -1 | cut -f2) \
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

```bash
GEMINI_API_KEY=your_key uvx --from git+https://github.com/Ritesh17rb/ffmpeg-transcriber transcribe -i ~/Documents/calls/call.opus
```

Or locally:

```bash
echo 'GEMINI_API_KEY=your_key' > .env
uv run transcribe -i ~/Documents/calls/call.opus
```

---

## How It Works

```
ffmpeg (Terminal 1)
  writes growing .opus file

transcribe (Terminal 2)
  polls file size every 1s
  probes duration with ffprobe
  extracts 5s WAV chunks via ffmpeg
  sends up to 4 chunks to Gemini in parallel
  prints results in timestamp order
  saves speech lines to transcript file
```

On startup, the transcriber detects if the file is actively growing and **jumps to the live position**. It **never exits** — keeps polling until you Ctrl+C. If you stop and restart, it **resumes from where it left off**.

Transcripts are saved to `~/Documents/transcripts/<name>_<date>.txt`.

---

## CLI Reference

```
transcribe -i <file.opus> [options]
```

| Flag | Default | Description |
|---|---|---|
| `-i`, `--input` | *(required)* | Path to the audio file being written |
| `-o`, `--output-dir` | `~/Documents/transcripts` | Where to save transcripts |
| `--no-save` | off | Print only, don't save files |
| `--chunk-seconds` | `5` | Audio chunk size per API call |
| `--from-start` | off | Start from beginning instead of live position |
| `--exit-after` | `0` | Exit after file stops growing for N seconds (0 = never) |
| `--model` | `gemini-2.5-flash` | Gemini model to use |

## Environment Variables

| Variable | Description |
|---|---|
| `GEMINI_API_KEY` | *(required)* Google AI API key |
| `GEMINI_MODEL` | Model override (default: `gemini-2.5-flash`) |
| `CHUNK_SECONDS` | Default chunk size |
| `TRANSCRIPT_DIR` | Default save directory |
