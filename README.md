# ffmpeg-transcriber

Records a call (mic + speaker) to disk and transcribes it live in the terminal using Gemini.

## Requirements

- Linux with PulseAudio
- FFmpeg: `sudo apt install ffmpeg`
- uv: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- A Google AI Studio API key — get one at [aistudio.google.com](https://aistudio.google.com/)

## Setup

1. Clone the repo:
   ```bash
   git clone https://github.com/Ritesh17rb/ffmpeg-transcriber
   cd ffmpeg-transcriber
   ```

2. Create a `.env` file:
   ```bash
   GEMINI_API_KEY=your_api_key_here
   ```

3. Find your speaker monitor device name:
   ```bash
   pactl list short sources | grep monitor
   ```
   If the name differs from the default, add it to `.env`:
   ```bash
   SPEAKER_DEVICE=your_monitor_device_name
   ```

## Run

```bash
uv run transcribe.py
```

- Press **Enter** to start — wear a headset to avoid echo
- Transcripts print live every ~5 seconds
- Recording saves to `~/Documents/calls/record-YYYY-MM-DD-HH-MM-SS.opus`
- Press **Ctrl+C** to stop

## How it works

A single FFmpeg process captures mic and speaker monitor simultaneously and produces two outputs:

- **Archival**: mixed stereo Opus file saved to `~/Documents/calls/`
- **Transcription**: raw PCM piped to the program → sent to Gemini every 5 seconds → printed to terminal
