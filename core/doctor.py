"""Ortam ve yapılandırma denetleyicisi.

    py -3.12 -m core.doctor

Eksikleri listeler, hiçbir şeyi değiştirmez. Kurulumdan sonra ve harici disk
değiştiğinde çalıştırılır.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

# n8n ve Node 22 burada yaşar — C:'de, harici diskte değil.
TOOLS_ROOT = Path(os.environ.get("LOCALAPPDATA", "")) / "otomasyon-tools"


@dataclass
class Result:
    name: str
    ok: bool
    detail: str
    fatal: bool = True


def _data_drive_present() -> bool:
    """Veri kökünün sürücüsü bağlı mı?

    Harici disk çıkarıldığında veri köküne bağlı her denetim ayrı ayrı patlar.
    Kök nedeni bir kez söyleyip gerisini atlamak, dört semptom listelemekten iyi.
    """
    from core import config

    anchor = Path(config.DATA_ROOT.anchor)
    return anchor.exists() if str(anchor) else config.DATA_ROOT.exists()


def _check_python() -> Result:
    v = sys.version_info
    ok = (v.major, v.minor) >= (3, 12)
    return Result(
        "Python >= 3.12",
        ok,
        f"{v.major}.{v.minor}.{v.micro} @ {sys.executable}",
    )


def _check_python_not_hijacked() -> Result:
    """PATH'teki `python` bu makinede başka bir uygulamanın venv'ine bağlı.

    Projede her zaman `py -3.12` veya venv'in kendi python.exe'si kullanılmalı.
    """
    which = shutil.which("python")
    if which is None:
        return Result(
            "`python` PATH kontrolü", True, "PATH'te `python` yok, sorun değil", fatal=False
        )
    hijacked = "hermes" in which.lower()
    return Result(
        "`python` PATH kontrolü",
        not hijacked,
        f"`python` -> {which}"
        + (" — BAŞKA UYGULAMANIN VENV'İ. `py -3.12` kullan." if hijacked else ""),
        fatal=False,
    )


def _check_ffmpeg() -> Result:
    exe = shutil.which("ffmpeg")
    if not exe:
        return Result("ffmpeg", False, "PATH'te bulunamadı")
    try:
        out = subprocess.run(
            [exe, "-version"], capture_output=True, text=True, timeout=15, check=False
        )
        first = out.stdout.splitlines()[0] if out.stdout else "sürüm okunamadı"
    except (subprocess.SubprocessError, OSError) as exc:
        return Result("ffmpeg", False, f"çalıştırılamadı: {exc}")
    return Result("ffmpeg", True, first)


def _check_node() -> Result:
    """Remotion Node 25 ile çalışır; n8n `>=20.19 <25` ister."""
    exe = shutil.which("node")
    if not exe:
        return Result("Node.js", False, "PATH'te bulunamadı")
    try:
        out = subprocess.run(
            [exe, "--version"], capture_output=True, text=True, timeout=15, check=False
        )
        ver = out.stdout.strip()
    except (subprocess.SubprocessError, OSError) as exc:
        return Result("Node.js", False, f"çalıştırılamadı: {exc}")

    try:
        major = int(ver.lstrip("v").split(".")[0])
    except (ValueError, IndexError):
        return Result("Node.js", True, f"{ver} (sürüm ayrıştırılamadı)", fatal=False)

    n8n_ok = 20 <= major < 25
    detail = f"{ver} — Remotion: uygun"
    detail += "; n8n: uygun" if n8n_ok else "; n8n bunu kullanamaz (taşınabilir Node 22'ye bak)"
    return Result("Node.js (sistem)", True, detail, fatal=False)


def _check_portable_node() -> Result:
    """n8n için taşınabilir Node 22.

    Sistem Node'u 25.x; n8n `>=20.19 <25` istiyor. nvm-windows sistem `node`
    komutunu devralacağı için kullanılmıyor — bunun yerine izole bir Node 22.

    C:'de yaşar, harici diskte değil: n8n'in bağımlılık ağacı 232 bin dosya ve
    exFAT/USB üzerinde kurulum pratikte bitmiyor (45 dakikada 31 MB).
    """
    node_home = TOOLS_ROOT / "node22"
    node_exe = node_home / "node.exe"

    if not node_exe.exists():
        return Result(
            "Node 22 (n8n için)",
            False,
            f"bulunamadı: {node_home} — `otomasyon setup-node` çalıştır",
            fatal=False,
        )

    try:
        out = subprocess.run(
            [str(node_exe), "--version"], capture_output=True, text=True, timeout=15, check=False
        )
        ver = out.stdout.strip()
    except (subprocess.SubprocessError, OSError) as exc:
        return Result("Node 22 (n8n için)", False, f"çalıştırılamadı: {exc}", fatal=False)

    n8n_cmd = TOOLS_ROOT / "npm-global" / "n8n.cmd"
    n8n_state = (
        "n8n kurulu" if n8n_cmd.exists() else "n8n kurulu değil (`scripts\\n8n.ps1 -Install`)"
    )
    return Result("Node 22 (n8n için)", True, f"{ver} — {n8n_state}", fatal=False)


def _check_config() -> list[Result]:
    try:
        from core import config
    except Exception as exc:
        return [Result("Yapılandırma", False, f"core.config yüklenemedi: {exc}")]

    results = [
        Result("Veri kökü", config.DATA_ROOT.exists(), str(config.DATA_ROOT)),
    ]

    missing = [d for d in config.ALL_DIRS if not d.exists()]
    results.append(
        Result(
            "Veri dizinleri",
            not missing,
            "hepsi mevcut" if not missing else f"eksik: {[str(d) for d in missing]}",
        )
    )

    problems = config.validate()
    results.append(
        Result(
            "Yapılandırma tutarlılığı",
            not problems,
            "sağlam" if not problems else " | ".join(problems),
        )
    )

    results.append(
        Result(
            "Onay kapısı",
            config.REQUIRE_HUMAN_APPROVAL,
            "AÇIK" if config.REQUIRE_HUMAN_APPROVAL else "KAPALI — kanal riske atılıyor",
        )
    )

    results.append(
        Result(
            "Kokoro TTS modeli",
            config.KOKORO_MODEL_PATH.exists(),
            str(config.KOKORO_MODEL_PATH)
            + (
                ""
                if config.KOKORO_MODEL_PATH.exists()
                else " — `core.voice --download-model` çalıştır"
            ),
            fatal=False,
        )
    )

    return results


def _check_disk() -> list[Result]:
    from core import config

    out: list[Result] = []
    for label, path in (("Kod diski (C:)", Path(__file__)), ("Veri diski", config.DATA_ROOT)):
        try:
            usage = shutil.disk_usage(path if path.is_dir() else path.parent)
        except OSError as exc:
            out.append(Result(label, False, f"okunamadı: {exc}"))
            continue
        free_gb = usage.free / (1024**3)
        # Kod diski için 5 GB, veri diski için 50 GB alt eşik
        floor = 5.0 if "Kod" in label else 50.0
        out.append(
            Result(
                label,
                free_gb >= floor,
                f"{free_gb:.1f} GB boş (alt eşik {floor:.0f} GB)",
                fatal=False,
            )
        )
    return out


def _check_youtube_auth() -> list[Result]:
    """Aktif kanalların YouTube yetkilendirmesi.

    Uyarı seviyesinde: yetkilendirme olmadan üretim sonuna kadar çalışır ve
    videolar onay kuyruğunda birikir. Yalnızca yükleme adımı durur.
    """
    from core import config, publish

    out: list[Result] = []
    for ch, profile in config.active_channels().items():
        path = publish.token_path(ch)
        ok = path.exists()
        out.append(
            Result(
                f"YouTube yetkisi ({profile.display_name})",
                ok,
                str(path) if ok else f"yok — `otomasyon authorize {ch.value}` çalıştır",
                fatal=False,
            )
        )
    return out


def _check_db() -> Result:
    try:
        from core import db

        if not db.db_exists():
            return Result(
                "Veritabanı", False, "henüz oluşturulmadı — `core.db.init()` çağır", fatal=False
            )
        s = db.stats()
        return Result(
            "Veritabanı",
            True,
            f"{s['total_jobs']} iş, bu ay ${s['month_spend_usd']:.2f} harcama",
            fatal=False,
        )
    except Exception as exc:
        return Result("Veritabanı", False, f"erişilemedi: {exc}", fatal=False)


def run() -> int:
    from core import config

    checks: list[Result] = [
        _check_python(),
        _check_python_not_hijacked(),
        _check_ffmpeg(),
        _check_node(),
        _check_portable_node(),
    ]

    if not _data_drive_present():
        # Kök neden. Veri köküne bağlı denetimler atlanır — hepsi aynı şeyi söylerdi.
        checks.append(
            Result(
                "Veri diski",
                False,
                f"{config.DATA_ROOT.anchor} bağlı değil. Harici diski tak, "
                f"veya .env içindeki OTOMASYON_DATA_ROOT'u güncelle. "
                f"(Veri kökü: {config.DATA_ROOT})",
            )
        )
        checks.append(
            Result(
                "Veri denetimleri",
                True,
                "disk bağlanana kadar atlandı",
                fatal=False,
            )
        )
    else:
        checks.extend(_check_config())
        checks.extend(_check_youtube_auth())
        checks.extend(_check_disk())
        checks.append(_check_db())

    width = max(len(c.name) for c in checks) + 2
    print("\n  OTOMASYON — ortam denetimi\n")
    for c in checks:
        mark = "OK  " if c.ok else ("HATA" if c.fatal else "UYAR")
        print(f"  [{mark}] {c.name.ljust(width)} {c.detail}")

    fatal = [c for c in checks if not c.ok and c.fatal]
    warn = [c for c in checks if not c.ok and not c.fatal]

    print()
    if fatal:
        print(f"  {len(fatal)} kritik sorun var — hat çalıştırılamaz.")
    elif warn:
        print(f"  Kritik sorun yok, {len(warn)} uyarı var.")
    else:
        print("  Her şey hazır.")
    print()

    return 1 if fatal else 0


if __name__ == "__main__":
    raise SystemExit(run())
