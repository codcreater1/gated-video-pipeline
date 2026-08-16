# Benchmarks

Real measurements taken on the reference machine (i5-9300H 4c/8t, 16 GB RAM, GTX 1650 4 GB, output written to an external SSD). Nothing here is an estimate — every number below was run and measured.

## Render — 13 August 2026

Remotion 4.x, `concurrency=3`, 1920×1080, h264, CRF 23.

| Visual layer | Speed | Measurement |
|---|---|---|
| Placeholder (gradient-heavy CSS) | 8.2 fps | 300 frames / 36.7 s |
| **Vector characters (current)** | **13.3 fps** | 600 frames / 45.0 s |

The vector layer came out **faster** than the gradient-heavy placeholder — SVG shapes are cheaper than full-screen radial gradients. The derivations below use the measured 13.3 fps:

| Job | Duration |
|---|---|
| 10-minute episode (18,000 frames) | **~23 minutes** |
| 12-minute episode (21,600 frames) | ~27 minutes |
| One episode per day | ~0.4 hours/day |
| Cold-start cadence (3/week) | ~1.1 hours/week |
| **60 minutes in a single pass** | **~2.3 hours** |

That last row is what validates the "long-form is concatenated, never rendered" decision: 40–60 minute compilations are produced from 8–12 minute episodes with `ffmpeg concat`, at a cost measured in seconds.

Output size is ~0.7 MB per 10 s → ~4 MB/min. A 10-minute episode is ~40 MB; the 1.4 TB external drive covers years of production.

> ⚠️ This number will drop as the visual layer gets richer (more assets, more layers). It must be re-measured when the art direction is upgraded.

The first render carries a one-off ~74 s overhead: Remotion downloads Chrome Headless Shell (113 MB) and compiles the bundle. Subsequent renders come from cache.

## Install times

| Package | Location | Files | Size | Duration |
|---|---|---|---|---|
| n8n 2.34.5 | Internal NVMe | 232,320 | 1.63 GB | a few minutes |
| n8n 2.34.5 | External exFAT/USB | — | 31 MB written | **cancelled after 45 min** |
| Remotion 4.x | Internal NVMe | 14,494 | 237 MB | 1 minute |

This table is why the "code on the internal drive, data on the external one" rule is hard rather than advisory. exFAT over USB becomes unusable at tens of thousands of small files.

## TTS

Kokoro-ONNX, CPU, `af_bella`, `speech_rate=0.82`:

| Measurement | Value |
|---|---|
| Generation speed | **~1.0× realtime** (32.5 s of audio in 33.2 s) |
| Model size | 310 MB (onnx) + 27 MB (voices) |
| Cost | $0 |

Realtime generation means a 10-minute episode takes ~10 minutes to narrate. Added to render time, that is ~33 minutes per episode.

## End to end — audio + video

13 August 2026, a 3-scene episode. Every stage real except the script.

| Stage | Duration |
|---|---|
| Narration (Kokoro, 3 scenes) | 33.2 s |
| Render (Remotion, 990 frames) | 81.4 s |
| **Total** | **114.6 s** |

Output: 33.0 s of video, 3.8 MB. **Audio/video drift 0.58 s** — it comes from rounding to whole seconds, stays inside the 2-second breathing margin, and causes no clipping.

> 🔑 **This test validated the most critical decision in the design.** The script estimated scene durations at 66 seconds; the actual narration came out at 32.5 seconds — a **2× error**. Had `core/narration.py` not rewritten the durations from measured audio length, the video would have run 33 seconds long on silence. Over a 10-minute episode that compounds into minutes of drift.

Per-episode projection (10-minute episode):

| | |
|---|---|
| Narration | ~10 min |
| Render | ~23 min |
| **Total** | **~33 min** |
| Cold-start cadence (3/week) | ~1.7 hours/week |
