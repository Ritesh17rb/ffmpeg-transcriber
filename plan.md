# Real-Time Audio Transcription Plan

## Task Understanding

Anand's intent is to keep the existing FFmpeg recording flow in one terminal and add a separate program in another terminal that prints live transcripts while the call is happening.

The existing FFmpeg command is only for archival recording. The new program should handle transcription in parallel, using either OpenAI or Gemini real-time speech-to-text APIs, and should display transcript updates continuously with low enough latency to be useful during a live conversation.

Two details from Anand's wording matter and should constrain the implementation:

- The second program must run in a separate terminal and fit around the existing recording workflow rather than replace it.
- The transcript should reflect the audio that is actually being recorded, not a loosely similar capture path, so the architecture needs a fallback if parallel device capture proves unreliable on the machine.

## Goal

Build a CLI program that:

- Runs independently from the FFmpeg recorder.
- Captures the same audio sources on Linux: microphone input and speaker monitor.
- Streams audio to a real-time transcription API.
- Prints partial and final transcripts as they arrive.
- Is simple to launch from a second terminal during a live call.
- Does not require the user to abandon Anand's existing `record` command.

## Recommended Direction

Use OpenAI first, with Gemini as a secondary option if needed.

Reasoning:

- OpenAI has a clear real-time API surface for streaming audio and receiving incremental transcription events.
- A terminal-first implementation is straightforward over WebSocket or SDK support.
- The output format can be normalized so the provider can be swapped later without changing the CLI behavior.

## Core Design

### Process Model

Keep two independent processes:

1. Terminal 1 runs the existing FFmpeg recorder.
2. Terminal 2 runs the live transcription program.

This preserves Anand's requested workflow and avoids coupling the recorder lifecycle to the transcription lifecycle.

The transcription program should support two operating modes:

1. Preferred: direct live capture from the relevant audio devices.
2. Fallback: transcribe the actively growing recording output if the Linux audio stack does not allow stable concurrent device reads.

That fallback matters because Anand framed the task as real-time transcription of the ongoing recording, not necessarily duplicate access to the same devices.

### Audio Capture

The transcription program should read from the same PulseAudio or PipeWire-exposed devices used by the recorder:

- Mic source: `default`
- Speaker source: `alsa_output.pci-0000_00_1f.3.analog-stereo.monitor`

It should mix them into a single mono or stereo stream suitable for speech recognition. For transcription, mono is usually sufficient and simpler.

Before implementation is considered correct, verify one operational point explicitly:

- Can FFmpeg recording and the transcription process both read these sources at the same time on the target machine without dropouts or device lock issues?

If not, the design should pivot to reading the active recording artifact or a tee'd raw stream rather than insisting on direct duplicate capture.

### Audio Preprocessing

Reuse the intent of Anand's FFmpeg filter chain, but simplify where possible for low-latency streaming:

- High-pass filter to reduce rumble.
- Optional denoise if it does not add noticeable delay.
- Mix mic and speaker into one stream.
- Resample to the API's accepted PCM rate, likely 16 kHz or 24 kHz mono PCM16.

The transcription path does not need Opus file encoding because it is optimized for streaming, not archival storage.

One caution:

- `loudnorm` is good for recording quality but may be too latency-heavy for live transcription.
- The transcription path should favor low-latency normalization or simple gain staging over offline-style processing.

### Streaming Model

The transcription CLI should:

- Read audio in short frames, such as 100 to 500 ms.
- Send frames continuously to the provider.
- Render partial transcript updates in-place when available.
- Print finalized transcript segments as stable lines with timestamps and speaker source markers if available.

It should also expose transcript event boundaries clearly enough that a user can follow the conversation in real time, not just dump raw incremental tokens noisily.

## Proposed Implementation Plan

### Phase 1: Provider and CLI Skeleton

- Pick the first provider implementation: OpenAI.
- Create a terminal CLI entry point such as `python main.py` or `node src/index.js`.
- Load API key and device names from environment variables or a small config file.
- Implement clean startup, shutdown, and reconnect behavior.
- Decide the canonical runtime contract up front:
  - `transcribe --mode live-devices`
  - `transcribe --mode follow-recording`

This keeps the fallback path explicit instead of treating it as an afterthought.

### Phase 2: Local Audio Ingest

- Capture audio from Linux audio devices without modifying the recording command.
- Validate that the mic and speaker monitor are both readable while FFmpeg is already recording.
- Build a local mixing pipeline.
- Convert the mixed stream to PCM chunks suitable for the API.

Recommended practical approach:

- Use FFmpeg as a subprocess for capture and preprocessing.
- Pipe raw PCM from FFmpeg into the transcription program.

This avoids rebuilding device handling manually and stays close to the already-working command Anand shared.

Fallback approach if concurrent device capture is unstable:

- Watch the most recent `.opus` output file from the recorder.
- Decode the growing file in short intervals with FFmpeg.
- Feed only newly available decoded PCM to the transcription stream.

This path is less elegant than direct live capture, but it adheres more closely to Anand's wording about transcribing the recording as it is being produced.

### Phase 3: Real-Time API Integration

- Open a persistent streaming session to the transcription provider.
- Send PCM frames as they are produced.
- Handle partial and final transcript events.
- Print results to stdout with minimal formatting noise.
- Normalize provider-specific events behind a local adapter so OpenAI and Gemini can share the same CLI behavior.

Suggested output format:

`[12:41:03] partial: okay wait i am just thinking`

`[12:41:05] final: okay wait, I am just thinking if I should...`

### Phase 4: Usability and Reliability

- Add CLI flags for mic device, speaker device, provider, and sample rate.
- Add a visible startup summary so the user knows which devices are active.
- Handle broken connections without crashing the whole process.
- Exit cleanly on `Ctrl+C`.
- Persist final transcript lines to a local text file as an optional flag for later review.
- Print a warning if headset use is recommended to avoid echo, matching Anand's note in the recorder flow.

### Phase 5: Validation

- Test with only mic audio.
- Test with only speaker monitor audio.
- Test with both sources during an actual call.
- Measure end-to-end latency from spoken words to displayed text.
- Verify that the transcript continues while the recorder is saving the `.opus` file in the other terminal.
- Verify that the transcript still works if the device names need to be changed from Anand's exact example.
- Compare direct-device mode against follow-recording mode and choose the lower-risk default.

## Technical Choices

### Language

Python is the fastest path unless there is already a strong preference for Node.js.

Reasoning:

- Fast to prototype subprocess audio pipelines.
- Mature WebSocket support.
- Simple terminal output handling.

### Capture Strategy

Preferred:

- FFmpeg subprocess outputs raw PCM to stdout.
- The app reads stdout in chunks and forwards it to the transcription API.

Fallback:

- Follow the growing recording output and decode incrementally.
- Native audio libraries such as PyAudio or sounddevice.

FFmpeg is preferable because the exact Linux device setup is already partially known and validated.

The important refinement is that the fallback should preserve transcript fidelity to the actual recording before exploring lower-level capture libraries.

### Transcript Rendering

Use two output modes:

- Partial mode for in-progress updates.
- Final mode for committed transcript lines.

If the provider exposes confidence or segment boundaries, include them only if they improve readability.

## Risks

- The monitor device name may vary across machines.
- Running two parallel readers on the same audio sources may behave differently across PulseAudio and PipeWire setups.
- Noise reduction filters may increase latency if they are too heavy.
- Real-time API behavior differs between OpenAI and Gemini, so the provider adapter should be isolated.
- Speaker diarization is likely out of scope for the first version unless the API provides it directly.
- Following a growing `.opus` file may introduce decoding edge cases or slightly higher latency than direct PCM capture.
- Partial transcript rendering can become unreadable if the CLI does not debounce or coalesce updates.

## Assumptions

- The machine is Linux-native, not WSL, for the main workflow.
- FFmpeg is already installed and working for audio capture.
- The user has an API key for at least one provider.
- Plain live transcript text in a terminal is sufficient for the first milestone.
- It is acceptable for version one to provide conversation-level transcription without speaker attribution.

## Deliverables

- A CLI transcription program runnable from a second terminal.
- Configuration for audio devices and provider credentials.
- Basic README usage instructions.
- A short test procedure showing how to run recorder plus transcription together.
- Documented fallback mode if simultaneous device access is not reliable.

## Execution Order

1. Confirm readable Linux audio device names on the target machine.
2. Prove whether the recorder and a second process can read the sources concurrently.
3. Implement the FFmpeg-to-PCM direct capture pipeline.
4. Add the follow-recording fallback path if concurrency is unstable.
5. Integrate OpenAI real-time transcription through a provider adapter.
6. Print partial and final transcript updates in the terminal with low-noise rendering.
7. Test concurrently with the existing recorder command.
8. Add Gemini support only if OpenAI is blocked or a provider comparison is explicitly needed.

## Success Criteria

The work is successful if, during a live call:

- Terminal 1 records the session to disk.
- Terminal 2 shows transcript updates within a few seconds.
- Both microphone and speaker audio are reflected in the transcript.
- The setup can be started reliably without modifying the user's normal call workflow.
- The transcript path remains usable even if Anand's exact device names do not match the target machine.
- If direct device capture fails, the fallback still produces live-enough transcripts from the active recording.
