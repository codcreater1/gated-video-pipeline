"""Render — Remotion'ı Python'dan tetikler ve uzun-form derlemeyi ffmpeg ile yapar.

İki ayrı iş:

1. `render_episode` — 8-12 dakikalık bir bölümü Remotion ile render eder.
2. `concat` — birden fazla bölümü ffmpeg ile 40-60 dakikalık derlemeye çevirir.

İkincisi neden ayrı: 60 dakikalık tek parça render bu makinede ~2.3 saat sürüyor
(ölçüldü, bkz. docs/benchmarks.md), oysa hazır bölümleri birleştirmek saniyeler.
Gerçek çocuk kanalları derlemeyi zaten böyle yapıyor.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from core import config

REMOTION_DIR = config.REPO_ROOT / "remotion"
COMPOSITION_ID = "BedtimeEpisode"
# Dikey Shorts. Boyutlar Remotion tarafında tanımlı (remotion/src/Root.tsx);
# `config.SHORTS_WIDTH/HEIGHT` ile eşleştikleri testle doğrulanıyor.
SHORT_COMPOSITION_ID = "BedtimeShort"

# Remotion Node 25 ile çalışıyor (n8n'in aksine) — sistem Node'u kullanılır.
# Render uzun sürer; bu sınır takılan bir işi sonsuza kadar beklememek için.
RENDER_TIMEOUT_SECONDS = 4 * 60 * 60


class RenderFailed(Exception):
    pass


@dataclass
class RenderResult:
    output_path: Path
    duration_seconds: float
    size_bytes: int
    elapsed_seconds: float

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


def _npx() -> str:
    exe = shutil.which("npx")
    if not exe:
        raise RenderFailed("npx bulunamadı — Node.js kurulu mu?")
    return exe


def _ffmpeg() -> str:
    exe = shutil.which("ffmpeg")
    if not exe:
        raise RenderFailed("ffmpeg bulunamadı.")
    return exe


def render_episode(
    job_id: int,
    storyboard: dict[str, Any],
    audio_dir: Path,
    output_path: Path | None = None,
    composition: str = COMPOSITION_ID,
) -> RenderResult:
    """Bir bölümü render eder.

    `audio_dir` Remotion'a `--public-dir` olarak verilir; storyboard'daki
    `audioSrc` alanları bu klasör içindeki dosya adlarıdır.

    `composition` yatay bölüm ile dikey Short arasında seçim yapar. Kadraj ve
    süre kompozisyonun kendi tanımından gelir; burada değişen tek şey kimlik.
    """
    import time

    if not (REMOTION_DIR / "node_modules").exists():
        raise RenderFailed(
            f"Remotion bağımlılıkları kurulu değil. Şunu çalıştır:\n"
            f"  cd {REMOTION_DIR} && npm install"
        )

    out = output_path or (config.OUTPUT_DIR / f"job_{job_id}.mp4")
    out.parent.mkdir(parents=True, exist_ok=True)

    # Props dosya üzerinden geçirilir — komut satırı argümanı olarak vermek
    # uzun storyboard'larda Windows'un komut uzunluğu sınırına takılıyor.
    with tempfile.NamedTemporaryFile(
        "w", suffix=".json", delete=False, encoding="utf-8"
    ) as tmp:
        json.dump(storyboard, tmp, ensure_ascii=False)
        props_path = Path(tmp.name)

    cmd = [
        _npx(), "remotion", "render", composition, str(out),
        f"--props={props_path}",
        f"--public-dir={audio_dir}",
        "--log=error",
    ]

    started = time.monotonic()
    try:
        proc = subprocess.run(
            cmd,
            cwd=REMOTION_DIR,
            capture_output=True,
            text=True,
            timeout=RENDER_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise RenderFailed(
            f"Render {RENDER_TIMEOUT_SECONDS // 3600} saatte bitmedi, durduruldu."
        ) from exc
    finally:
        props_path.unlink(missing_ok=True)

    elapsed = time.monotonic() - started

    if proc.returncode != 0:
        tail = (proc.stderr or proc.stdout or "").strip()[-1500:]
        raise RenderFailed(f"Remotion çıkış kodu {proc.returncode}:\n{tail}")

    if not out.exists():
        raise RenderFailed(f"Remotion 0 döndü ama dosya oluşmadı: {out}")

    return RenderResult(
        output_path=out,
        duration_seconds=probe_duration(out),
        size_bytes=out.stat().st_size,
        elapsed_seconds=elapsed,
    )


def render_short(
    job_id: int,
    storyboard: dict[str, Any],
    audio_dir: Path,
    output_path: Path | None = None,
) -> RenderResult:
    """Dikey Short render eder — 1080×1920.

    Ayrı bir fonksiyon çünkü çıktı yolu da ayrı: Short'lar bölümlerle aynı
    dizinde aynı adlandırmayı kullanırsa `job_<id>.mp4` çakışmaz ama insan
    gözüyle ayırt edilemez hale gelir.
    """
    out = output_path or (config.OUTPUT_DIR / f"short_{job_id}.mp4")
    return render_episode(
        job_id=job_id,
        storyboard=storyboard,
        audio_dir=audio_dir,
        output_path=out,
        composition=SHORT_COMPOSITION_ID,
    )


def probe_duration(path: Path) -> float:
    """Video süresini ffprobe ile okur. QC kapısı bunu doğrular."""
    exe = shutil.which("ffprobe")
    if not exe:
        return 0.0
    proc = subprocess.run(
        [
            exe, "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    try:
        return float((proc.stdout or "0").strip())
    except ValueError:
        return 0.0


def concat(episode_paths: list[Path], output_path: Path) -> RenderResult:
    """Bölümleri tek derlemede birleştirir — yeniden kodlama YOK.

    Tüm bölümler aynı codec/çözünürlük/fps ile render edildiği için stream copy
    yeterli. Yeniden kodlamak hem saatler sürer hem kaliteyi düşürürdü.
    """
    import time

    if not episode_paths:
        raise RenderFailed("Birleştirilecek bölüm yok.")
    missing = [p for p in episode_paths if not p.exists()]
    if missing:
        raise RenderFailed(f"Eksik bölüm dosyaları: {missing}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.NamedTemporaryFile(
        "w", suffix=".txt", delete=False, encoding="utf-8"
    ) as tmp:
        for p in episode_paths:
            # ffmpeg concat biçimi: tek tırnak kaçışı gerektirir
            safe = str(p.resolve()).replace("'", r"'\''")
            tmp.write(f"file '{safe}'\n")
        list_path = Path(tmp.name)

    started = time.monotonic()
    try:
        proc = subprocess.run(
            [
                _ffmpeg(), "-hide_banner", "-loglevel", "error", "-y",
                "-f", "concat", "-safe", "0", "-i", str(list_path),
                "-c", "copy", str(output_path),
            ],
            capture_output=True,
            text=True,
            timeout=30 * 60,
            check=False,
        )
    finally:
        list_path.unlink(missing_ok=True)

    elapsed = time.monotonic() - started

    if proc.returncode != 0:
        raise RenderFailed(
            f"ffmpeg concat çıkış kodu {proc.returncode}:\n{(proc.stderr or '')[-1000:]}"
        )

    return RenderResult(
        output_path=output_path,
        duration_seconds=probe_duration(output_path),
        size_bytes=output_path.stat().st_size,
        elapsed_seconds=elapsed,
    )
