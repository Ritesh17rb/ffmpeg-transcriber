# Realtime Audio Transcription

Run Anand's recorder in one terminal and this in another:

```bash
npm install
npm start
```

Or with explicit overrides:

```bash
node transcribe.js --mic default --speaker alsa_output.pci-0000_00_1f.3.analog-stereo.monitor
```

### Required `.env` key

```bash
GEMINI_API_KEY=<your Google AI Studio key>
```

### Optional `.env` overrides

```bash
GEMINI_MODEL=models/gemini-2.0-flash-exp
MIC_DEVICE=default
SPEAKER_DEVICE=alsa_output.pci-0000_00_1f.3.analog-stereo.monitor
TRANSCRIPTION_LANGUAGE=en
```

### Output format

```
[14:32:01] Okay wait, I am just thinking if I should...
[14:32:04] Yeah, I have worked with this but I can explore.
```

Partial updates scroll in-place on the same line; finalized lines are printed with a timestamp.
