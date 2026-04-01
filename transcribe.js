#!/usr/bin/env node

const fs = require("node:fs");
const path = require("node:path");
const { spawn } = require("node:child_process");
const https = require("node:https");

// Load .env
const envPath = path.join(process.cwd(), ".env");
if (fs.existsSync(envPath)) {
  for (const line of fs.readFileSync(envPath, "utf8").split(/\r?\n/)) {
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("#")) continue;
    const sep = trimmed.indexOf("=");
    if (sep === -1) continue;
    const key = trimmed.slice(0, sep).trim();
    const val = trimmed.slice(sep + 1).trim().replace(/^["']|["']$/g, "");
    if (key && process.env[key] === undefined) process.env[key] = val;
  }
}

const API_KEY      = process.env.GEMINI_API_KEY || "";
const MIC          = process.env.MIC_DEVICE     || "default";
const SPEAKER      = process.env.SPEAKER_DEVICE || "alsa_output.pci-0000_00_1f.3.analog-stereo.monitor";
const SAMPLE_RATE  = 16000;
const CHUNK_MS     = 5000;
const CHUNK_BYTES  = (SAMPLE_RATE * 2 * CHUNK_MS) / 1000; // s16le mono

if (!API_KEY) {
  console.error("Missing GEMINI_API_KEY in .env");
  process.exit(1);
}

const GEMINI_URL = `https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key=${API_KEY}`;

let pcmBuffer    = Buffer.alloc(0);
let shuttingDown = false;

console.log(`Mic: ${MIC}`);
console.log(`Speaker: ${SPEAKER}`);
console.log("Listening… (Ctrl+C to stop)\n");

// Start FFmpeg
const ffmpeg = spawn("ffmpeg", [
  "-hide_banner", "-loglevel", "error",
  "-f", "pulse", "-i", MIC,
  "-f", "pulse", "-i", SPEAKER,
  "-filter_complex",
    "[0:a]highpass=f=100,lowpass=f=12000,afftdn=nf=-30,volume=2[m];" +
    "[1:a]pan=mono|c0=FR[s];" +
    "[m][s]amix=inputs=2:weights=1 1:normalize=0,aresample=16000,aformat=sample_fmts=s16:channel_layouts=mono,asetpts=N/SR/TB[a]",
  "-map", "[a]",
  "-f", "s16le", "-acodec", "pcm_s16le", "-ac", "1", "-ar", "16000",
  "pipe:1",
], { stdio: ["ignore", "pipe", "pipe"] });

ffmpeg.stdout.on("data", (chunk) => {
  pcmBuffer = Buffer.concat([pcmBuffer, chunk]);
  while (pcmBuffer.length >= CHUNK_BYTES) {
    transcribe(pcmBuffer.subarray(0, CHUNK_BYTES));
    pcmBuffer = pcmBuffer.subarray(CHUNK_BYTES);
  }
});

ffmpeg.stderr.on("data", (d) => {
  const msg = d.toString().trim();
  if (msg) console.error(`[ffmpeg] ${msg}`);
});

ffmpeg.on("exit", (code) => {
  if (!shuttingDown) {
    console.error(`ffmpeg exited (code=${code})`);
    process.exit(1);
  }
});

process.on("SIGINT",  () => shutdown());
process.on("SIGTERM", () => shutdown());

// Send PCM chunk to Gemini and print transcript
function transcribe(pcm) {
  const wav = toWav(pcm);
  const ts  = new Date().toLocaleTimeString("en-GB", { hour12: false });

  const body = JSON.stringify({
    contents: [{ parts: [
      { inlineData: { mimeType: "audio/wav", data: wav.toString("base64") } },
      { text: "Transcribe the speech exactly as spoken. Output only the spoken words. If silence, output nothing." },
    ]}],
    generationConfig: { temperature: 0 },
  });

  const url = new URL(GEMINI_URL);
  const req = https.request({
    hostname: url.hostname,
    path: url.pathname + url.search,
    method: "POST",
    headers: { "Content-Type": "application/json", "Content-Length": Buffer.byteLength(body) },
  }, (res) => {
    let data = "";
    res.on("data", (d) => data += d);
    res.on("end", () => {
      try {
        const json = JSON.parse(data);
        if (json.error) { console.error(`API error: ${json.error.message}`); return; }
        const text = json.candidates?.[0]?.content?.parts?.[0]?.text?.trim();
        if (text && /\w/.test(text)) console.log(`[${ts}] ${text}`);
      } catch (e) {
        console.error(`Parse error: ${e.message}`);
      }
    });
  });
  req.on("error", (e) => console.error(`Request error: ${e.message}`));
  req.write(body);
  req.end();
}

// Wrap raw PCM s16le in a WAV header
function toWav(pcm) {
  const header = Buffer.alloc(44);
  header.write("RIFF", 0);
  header.writeUInt32LE(36 + pcm.length, 4);
  header.write("WAVE", 8);
  header.write("fmt ", 12);
  header.writeUInt32LE(16, 16);
  header.writeUInt16LE(1, 20);   // PCM
  header.writeUInt16LE(1, 22);   // mono
  header.writeUInt32LE(SAMPLE_RATE, 24);
  header.writeUInt32LE(SAMPLE_RATE * 2, 28);
  header.writeUInt16LE(2, 32);
  header.writeUInt16LE(16, 34);
  header.write("data", 36);
  header.writeUInt32LE(pcm.length, 40);
  return Buffer.concat([header, pcm]);
}

function shutdown() {
  if (shuttingDown) return;
  shuttingDown = true;
  if (!ffmpeg.killed) ffmpeg.kill("SIGTERM");
  setTimeout(() => process.exit(0), 500);
}
