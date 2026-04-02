# livetrans

Records a call (mic + speaker) to disk and transcribes it live in the terminal using Gemini.

## Requirements

- Linux with PulseAudio
- [FFmpeg](https://ffmpeg.org/download.html) (`sudo apt install ffmpeg`)
- [uv](https://docs.astral.sh/uv/getting-started/installation/)
- A [Google AI Studio](https://aistudio.google.com/) API key

## Setup

1. Clone the repo and enter it:
   ```bash
   git clone <repo-url>
   cd livetrans
   ```

2. Create a `.env` file:
   ```bash
   GEMINI_API_KEY=your_api_key_here
   ```

   Optional overrides (defaults work for most Linux setups):
   ```bash
   MIC_DEVICE=default
   SPEAKER_DEVICE=alsa_output.pci-0000_00_1f.3.analog-stereo.monitor
   ```

3. Find your speaker monitor device name if the default doesn't work:
   ```bash
   pactl list short sources | grep monitor
   ```
   Copy the name and set it as `SPEAKER_DEVICE` in `.env`.

## Usage

```bash
uv run transcribe.py
```

- Press **Enter** to start (wear a headset to avoid echo)
- Transcripts print live every ~5 seconds
- Recording saves to `~/Documents/calls/record-YYYY-MM-DD-HH-MM-SS.opus`
- Press **Ctrl+C** to stop

## How it works

A single FFmpeg process captures mic and speaker monitor simultaneously and produces two outputs:

- **Archival**: mixed stereo Opus file saved to `~/Documents/calls/`
- **Transcription**: raw PCM piped to the program → sent to Gemini every 5 seconds → printed to terminal
