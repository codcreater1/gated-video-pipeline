# Setup

This document was written against the phase-0 audit of one reference machine. On different hardware, re-run the "Environment audit" section before trusting the decisions that follow from it.

## Reference machine (audited 13 August 2026)

| Component | State |
|---|---|
| CPU | Intel i5-9300H, 4 cores / 8 threads |
| RAM | 15.9 GB |
| GPU | NVIDIA GTX 1650, **4 GB VRAM** (driver 528.02) |
| System drive (code) | 237 GB NVMe, **17.1 GB free** |
| External drive (data) | 1.86 TB USB, **1.4 TB free**, exFAT |
| Python | `py -3.12` → 3.12.10 ✅ |
| uv | 0.11.29 ✅ |
| Node | **25.9.0 — too new for n8n** ⚠️ |
| ffmpeg | 8.1.2-full ✅ |
| git | 2.54.0 ✅ |
| Docker | Not installed, **WSL broken** (`REGDB_E_CLASSNOTREG`) ❌ |

## Three decisions that follow from it

**1. No Docker.** WSL is broken and Docker Desktop wants ~10 GB the system drive does not have. n8n is installed via npm — an officially supported path.

**2. Do not rely on the bare `python` command.** On this machine `python` resolved to an unrelated application's virtualenv with no pip. Always use **`py -3.12`** or the project venv's own `python.exe`.

**3. Code on the internal drive, data on the external one.** `node_modules` and virtualenvs behave badly on exFAT (tens of thousands of small files, no symlink support). Render output, models and assets are large files — exactly what the external drive is for.

---

## Step 1 — Node 22 (for n8n)

n8n requires `>=20.19 <25`; this machine has 25.9.0, which Remotion needs.

**nvm-windows was not used and should not be.** It takes over the `node` command of an existing installation; with a normally installed Node 25 already present, that causes confusion on the Remotion side.

A **portable Node 22** is used instead:

```
%LOCALAPPDATA%\otomasyon-tools\node22\       # Node v22.23.2 LTS "Jod"
%LOCALAPPDATA%\otomasyon-tools\npm-global\   # n8n 2.34.5 (~1.6 GB)
%LOCALAPPDATA%\otomasyon-tools\n8n\          # n8n data (workflows, credentials, SQLite)
```

The system PATH is untouched, no admin rights are needed, and the Node 25 installation is left alone. The n8n launcher puts this Node first only within its own session.

> ⚠️ **Why are these on the internal drive, despite the "data on the external drive" rule?** The first attempt installed npm-global onto the external drive and managed **31 MB in 45 minutes**. n8n's dependency tree is **232,320 files**; exFAT over USB cannot handle that many small files in practice. The same install finished in minutes on the internal NVMe.
>
> The "data on the external drive" rule is for **heavy media**: render output, TTS models, assets. n8n's state is a few tens of MB and operationally critical — n8n failing to start whenever the external drive is unplugged is not acceptable.

To install on another machine:

```bash
py -3.12 -m core.cli setup-node
```

Or manually: download `node-v22.x.x-win-x64.zip` from [nodejs.org/dist](https://nodejs.org/dist/) and extract it as `%LOCALAPPDATA%\otomasyon-tools\node22`.

## Step 2 — Python environment

From the repository root:

```bash
uv venv --python 3.12 .venv
```

```bash
.venv\Scripts\activate
```

The core logic installs without the heavy runtime dependencies — enough to run the full test suite:

```bash
uv pip install -e ".[dev]"
```

For actual production, add the runtime extra (Kokoro TTS + YouTube client):

```bash
uv pip install -e ".[runtime,dev]"
```

## Step 3 — Configuration

Copy `.env.example` to `.env` and fill it in:

```bash
copy .env.example .env
```

Minimum required:

- `OTOMASYON_DATA_ROOT` — the data root on the external drive. `core.config` raises at import time if this is unset; there is deliberately no silent default.
- `ANTHROPIC_API_KEY` — for script generation
- `YT_CLIENT_SECRET_FILE` — for YouTube upload (Step 5)

`KLING_API_KEY` may be left empty; the pipeline then falls back entirely to asset-pack rendering and spends $0 on AI video.

## Step 4 — Verification

```bash
py -3.12 -m core.doctor
```

This audits configuration, directories, the external drive, ffmpeg and the model files, and lists what is missing.

## Step 5 — YouTube OAuth

1. Create a project in the [Google Cloud Console](https://console.cloud.google.com/)
2. Enable the **YouTube Data API v3**
3. Create an OAuth 2.0 Client ID → type: **Desktop app** → download the JSON
4. Point `YT_CLIENT_SECRET_FILE` in `.env` at that JSON
5. Authorize each active channel once — this opens a browser:

```bash
otomasyon authorize bedtime
```

The token is written to `$OTOMASYON_DATA_ROOT/credentials/`, outside the repository, so committing it is not physically possible. `YT_CHANNEL_A_TOKEN_FILE` in `.env` overrides the location if you want it elsewhere.

Two scopes are requested, and both are used: `youtube.upload` for publishing and `yt-analytics.readonly` for the post-publish feedback loop. They are requested together so the consent screen appears once per channel.

> If you authorized a channel before the analytics scope was added, the existing token is valid but insufficient. `otomasyon analytics --refresh` will say so explicitly rather than returning a bare 403 — re-run `otomasyon authorize <channel>` to add the scope.

> ⚠️ The most common mistake here is signing in with the wrong Google account. The browser page shows which channel is being authorized — check it before approving.

Once authorized, `otomasyon doctor` reports the token for each active channel, and publishing works:

```bash
otomasyon uploads
```

```bash
otomasyon publish 1
```

Once an episode is published you can derive the two cheaper formats from it — neither calls an LLM:

```bash
otomasyon short 1
```

```bash
otomasyon compile
```

`short` takes one scene of a published episode, trims its narration at a sentence boundary and re-renders it vertically at 1080×1920. `compile` concatenates published episodes into a 40–60 minute assembly with `ffmpeg` stream copy. Both land in the same approval queue as episodes.

Once episodes are at least 7 days old, pull their performance and see the weights it feeds back into ideation:

```bash
otomasyon analytics --refresh
```

> Quota note: `videos.insert` dropped from ~1600 to ~100 units on 4 December 2025, and since 1 June 2026 it has had its own daily bucket (~100 calls/day). It no longer competes with the read/search budget and is not a bottleneck at this volume — the pipeline's own daily ceiling is 2 long-form videos.

## Step 6 — Kokoro TTS model

```bash
py -3.12 -m core.voice --download-model
```

The model lands under `$OTOMASYON_DATA_ROOT\models\kokoro\` (~350 MB). It uses the ONNX runtime — no PyTorch or CUDA required.

> The GTX 1650's 4 GB of VRAM is not enough for Chatterbox, which is why Kokoro was chosen. At 82M parameters it runs comfortably on CPU and is already one of the strongest open-source options for narration.

## Step 7 — Remotion

```bash
cd remotion
```

```bash
npm install
```

Preview:

```bash
npm run studio
```

Render a single frame (this is how `docs/images/hero.png` was produced):

```bash
npx remotion still BedtimeEpisode ../docs/images/hero.png --frame=3700
```

## Step 8 — n8n

Install once:

```bash
.\scripts\n8n.ps1 -Install
```

Start:

```bash
.\scripts\n8n.ps1
```

Interface: http://127.0.0.1:5678

Check the version:

```bash
.\scripts\n8n.ps1 -Version
```

All of n8n's state — workflows, credentials, its own SQLite database — lives under `%LOCALAPPDATA%\otomasyon-tools\n8n\`, set by `N8N_USER_FOLDER` in [`scripts/n8n.ps1`](../scripts/n8n.ps1). Global npm packages go to `%LOCALAPPDATA%\otomasyon-tools\npm-global\`. See the warning in Step 1 for why these are not on the external drive.

> n8n Community Edition is free under the Sustainable Use License: no workflow or execution limits, 400+ integrations and the Code node included. The only restriction is reselling n8n to third parties as a hosted service, which does not apply here.
