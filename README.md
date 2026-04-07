# ffmpeg-transcriber

Follows a growing `.opus` call recording and prints Gemini transcripts in near real time.

## Requirements

- Linux with PulseAudio
- FFmpeg + FFprobe: `sudo apt install ffmpeg`
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

3. Sync the project:
   ```bash
   uv sync
   ```

## Run With The Repo Checked Out

Start the recorder in one terminal and write to a fixed file path:

```bash
mkdir -p ~/Documents/calls

ffmpeg -hide_banner -stats -v error \
  -f pulse -i default \
  -f pulse -i alsa_output.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__hw_sofhdadsp__sink.monitor \
  -filter_complex "\
    [0:a]highpass=f=100,lowpass=f=12000,afftdn=nf=-30,volume=2[m]; \
    [1:a]pan=mono|c0=FR[s]; \
    [m][s]amerge,loudnorm=I=-16:LRA=7:tp=-1[a]" \
  -map "[a]" \
  -ar 48000 \
  -ac 2 \
  -c:a libopus \
  -b:a 24k \
  "$HOME/Documents/calls/live-test.opus"
```

In another terminal, start the transcriber against that same file:

```bash
uv run transcribe -i ~/Documents/calls/live-test.opus
```

## Run Without Cloning

Run directly from GitHub:

```bash
uvx --from git+https://github.com/Ritesh17rb/ffmpeg-transcriber transcribe -i ~/Documents/calls/live-test.opus
```

Use `uv run` when you already have this repo checked out locally. Use `uvx --from ...` when you want uv to fetch the package from Git and run the `transcribe` command for you without a clone.

## Behavior

- Start the recorder in one terminal.
- Start the transcriber in another terminal, pointed at the same `.opus` file.
- The transcriber stays 5 seconds behind the writer by default.
- The recorder should flush output regularly, ideally every 5 seconds.
- Default Gemini model: `gemini-2.5-flash`.
- When the input file stops growing, the script transcribes the tail and exits.

## How it works

- `ffprobe` checks how much audio is currently available in the growing file.
- The script stays one chunk behind the writer, so it only reads completed audio.
- `ffmpeg` extracts each ready chunk, converts it to mono 16 kHz WAV, and the script sends that chunk to Gemini.

## Notes

- This repo no longer owns the recording step.
- The input contract is now a specific `.opus` file path, not live microphone devices.
