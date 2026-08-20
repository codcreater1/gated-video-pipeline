"""Shorts ve derleme — üretilebilir olmayan iki formatın testleri.

Bu iki format uzun süre config'de tanımlıydı ama üretilemiyordu: `render.concat`
yazılmıştı ve hiçbir yerden çağrılmıyordu, `SHORTS_WIDTH/HEIGHT` hiçbir yerde
kullanılmıyordu. Buradaki testlerin çoğu o boşluğun geri açılmasını engelliyor.

Asıl mimari değişiklik varyasyon kapısının FORMAT ŞERİDİNE ayrılması. Bir
Short metnini kaynak bölümünden türetir; kapı format ayrımı yapmasaydı hiçbir
Short yayınlanamazdı — ve bu, kapı "çalışıyor" göründüğü için sessizce olurdu.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

from core import compilation, config, db, narration, shorts, storyboard, variation_guard

SENTENCES = (
    "Fen found a long grey feather resting on a wet stone. "
    "It was not the otter's feather, and somewhere a bird was missing it. "
    "Fen followed the water until a tall bird stood in the shallows. "
    "The heron tucked the feather back into her wing and the stream went quiet. "
) * 3


@pytest.fixture(autouse=True)
def temp_dirs(tmp_path, monkeypatch):
    for name in (
        "PENDING_DIR", "APPROVED_DIR", "REJECTED_DIR", "PUBLISHED_DIR",
        "OUTPUT_DIR", "CACHE_DIR",
    ):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(config, name, d)


def _episode(
    tmp_path: Path,
    title: str = "Fen and the Lost Feather",
    narration_text: str = SENTENCES,
    duration: int = 600,
    published: bool = True,
    with_file: bool = True,
    voice_id: str = "af_bella",
    day_offset: int = 0,
) -> int:
    """Yayınlanmış, dosyası diskte olan bir bölüm kurar."""
    job_id = db.create_job("bedtime", "episode")
    out = tmp_path / f"job_{job_id}.mp4"
    if with_file:
        out.write_bytes(b"\x00" * 512)

    board = {
        "premise": {
            "setting": "sessiz orman", "character": "sessiz tilki",
            "shape": "keşif", "protagonist": "Fen",
        },
        "title": title,
        "description": "A gentle bedtime story.",
        "scenes": [
            {
                "index": i,
                "narration": narration_text,
                "setting": "sessiz orman",
                "action": "looks around",
                "mood": "calm",
                "duration_seconds": duration // 3,
                "transition": "fade",
                "assets": {
                    "background": "bg/sessiz_orman/soft",
                    "character": "char/su_samuru/looking",
                    "companion": "char/sessiz_tilki/looking",
                },
                "audioSrc": f"scene_{i}.wav",
                "audioDelaySeconds": 1.2,
            }
            for i in range(3)
        ],
    }
    db.update_job(
        job_id,
        status=db.JobStatus.PUBLISHED.value if published else db.JobStatus.QUEUED.value,
        title=title,
        script=narration_text,
        storyboard_json=json.dumps(board, ensure_ascii=False),
        voice_id=voice_id,
        duration_seconds=duration,
        output_path=str(out) if with_file else None,
        youtube_video_id=f"vid{job_id:04d}",
        published_at=datetime.now(UTC).replace(microsecond=day_offset).isoformat(),
    )
    return job_id


def fake_narrator(total_seconds: float = 38.0, voice_id: str = "af_bella"):
    """Kokoro çalıştırmaz. Süreyi test kontrol eder — asıl denetlenen şey o."""

    def _narrate(job_id, board, channel, voice=None):
        scenes = [
            {**s, "audioSrc": f"scene_{s['index']}.wav", "audioDelaySeconds": 1.2}
            for s in board.get("scenes", [])
        ]
        return narration.NarrationResult(
            storyboard={**board, "scenes": scenes},
            audio_dir=config.CACHE_DIR / "tts" / f"job_{job_id}",
            voice_id=voice or voice_id,
            total_seconds=total_seconds,
            scene_count=len(scenes),
        )

    return _narrate


def fake_renderer(tmp_path: Path):
    def _render(job_id, board, audio_dir):
        out = tmp_path / f"short_{job_id}.mp4"
        out.write_bytes(b"\x00" * 256)
        return out

    return _render


# --------------------------------------------------------------------------
# Shorts — kaynak seçimi
# --------------------------------------------------------------------------

def test_yayinlanmamis_bolumden_short_turetilemez(tmp_path):
    """Onay kapısından geçmemiş içeriği Short olarak kanala sokmak,
    kapıyı arka kapıdan atlatmak olurdu."""
    parent = _episode(tmp_path, published=False)

    with pytest.raises(shorts.ShortError, match="yayınlanmamış"):
        shorts.plan(parent)


def test_short_yalnizca_bolumden_turetilir(tmp_path):
    parent = _episode(tmp_path)
    db.update_job(parent, format="compilation")

    with pytest.raises(shorts.ShortError, match="yalnızca bölümden"):
        shorts.plan(parent)


def test_olmayan_sahne_net_hata_verir(tmp_path):
    parent = _episode(tmp_path)

    with pytest.raises(shorts.ShortError, match="Sahne 9 yok"):
        shorts.plan(parent, scene_index=9)


# --------------------------------------------------------------------------
# Shorts — anlatım kısaltma
# --------------------------------------------------------------------------

def test_anlatim_cumle_sinirinda_kesilir(tmp_path):
    """Karakterle kesmek cümle ortasında bırakıyordu ve seslendirme
    yarım bir cümleyle bitiyordu."""
    parent = _episode(tmp_path)
    p = shorts.plan(parent)

    assert p.narration_text.rstrip().endswith((".", "!", "?"))
    assert len(p.narration_text) < len(SENTENCES)


def test_hedefi_asan_tek_cumle_bile_korunur():
    """Cümlesiz bir Short üretmektense hedefi aşmak yeğdir."""
    uzun = "A single sentence that runs on and on and keeps going past any target."
    kept = shorts._trim_to_fit(uzun, speech_rate=0.82, target=1.0)

    assert kept.strip() == uzun.strip()


def test_bos_anlatim_reddedilir():
    with pytest.raises(shorts.ShortError, match="boş"):
        shorts._trim_to_fit("   ", speech_rate=0.82, target=30.0)


def test_short_sahnesi_sifirdan_numaralanir(tmp_path):
    """Ses dosyaları `scene_<index>.wav` adlanıyor; kaynak index'i korumak
    seslendirmeyi olmayan bir dosyaya bağlardı."""
    parent = _episode(tmp_path)
    p = shorts.plan(parent, scene_index=2)

    assert len(p.storyboard["scenes"]) == 1
    assert p.storyboard["scenes"][0]["index"] == 0


def test_short_kaynak_bolume_baglanir(tmp_path):
    parent = _episode(tmp_path)
    p = shorts.plan(parent)

    assert p.storyboard["short_of"] == parent


# --------------------------------------------------------------------------
# Shorts — üretim
# --------------------------------------------------------------------------

def test_short_isi_kurulur_ve_render_edilir(tmp_path):
    parent = _episode(tmp_path)

    job_id, _ = shorts.create(
        parent, narrator=fake_narrator(38.0), renderer=fake_renderer(tmp_path)
    )

    row = db.get_job(job_id)
    assert row["format"] == "short"
    assert row["duration_seconds"] == 38
    assert Path(row["output_path"]).exists()


def test_short_kaynak_bolumun_sesini_kullanir(tmp_path):
    """Short ile bölüm farklı anlatıcıyla çıkarsa iki ayrı kanal gibi duruyor."""
    parent = _episode(tmp_path, voice_id="bf_emma")
    gelen: list[str | None] = []

    def spy(job_id, board, channel, voice=None):
        gelen.append(voice)
        return fake_narrator(38.0)(job_id, board, channel, voice)

    shorts.create(parent, narrator=spy, renderer=fake_renderer(tmp_path))

    assert gelen == ["bf_emma"]


@pytest.mark.parametrize("saniye", [12.0, 75.0])
def test_format_disi_sure_reddedilir_ve_is_kaybolmaz(tmp_path, saniye):
    """20-59 saniye dışı bir video Shorts rafına hiç girmez."""
    parent = _episode(tmp_path)

    with pytest.raises(shorts.ShortError, match="aralık dışında"):
        shorts.create(
            parent, narrator=fake_narrator(saniye), renderer=fake_renderer(tmp_path)
        )

    reddedilen = db.jobs_by_status(db.JobStatus.REJECTED)
    assert len(reddedilen) == 1
    assert "SHORTS SÜRESİ" in reddedilen[0]["rejection_reason"]


def test_format_disi_surede_render_calismaz(tmp_path):
    """Render en pahalı adım; süre denetimi ondan önce olmalı."""
    parent = _episode(tmp_path)
    cagrildi = []

    def renderer(job_id, board, audio_dir):
        cagrildi.append(job_id)
        return tmp_path / "x.mp4"

    with pytest.raises(shorts.ShortError):
        shorts.create(parent, narrator=fake_narrator(90.0), renderer=renderer)

    assert not cagrildi


# --------------------------------------------------------------------------
# Varyasyon kapısı — format şeridi
# --------------------------------------------------------------------------

def _publish_fingerprint(job_id: int, fmt: str) -> None:
    row = db.get_job(job_id)
    board = json.loads(row["storyboard_json"])
    variation_guard.commit_fingerprint(
        job_id=job_id,
        channel="bedtime",
        storyboard=board,
        title=row["title"] or "",
        asset_ids=storyboard.variation_asset_ids(board),
        voice_id=row["voice_id"] or "af_bella",
        fmt=fmt,
    )


def test_short_kaynak_bolumuyle_karsilastirilmaz(tmp_path):
    """KRİTİK: Short metnini bölümden türetiyor. Şerit olmasaydı benzerlik
    tavan yapar ve hiçbir Short kapıdan geçemezdi."""
    parent = _episode(tmp_path)
    _publish_fingerprint(parent, "episode")

    job_id, p = shorts.create(
        parent, narrator=fake_narrator(38.0), renderer=fake_renderer(tmp_path)
    )
    row = db.get_job(job_id)
    board = json.loads(row["storyboard_json"])

    verdict = variation_guard.evaluate(
        channel="bedtime",
        script=p.narration_text,
        storyboard=board,
        title=row["title"] or "",
        asset_ids=storyboard.variation_asset_ids(board),
        voice_id="af_bella",
        fmt="short",
    )

    assert verdict.passed, verdict.reason


def test_serit_olmadan_ayni_short_reddedilirdi(tmp_path):
    """Şeridin gerçekten iş yaptığının kanıtı: format filtresi kalkınca
    aynı içerik kapıda kalıyor."""
    parent = _episode(tmp_path)
    _publish_fingerprint(parent, "episode")
    job_id, p = shorts.create(
        parent, narrator=fake_narrator(38.0), renderer=fake_renderer(tmp_path)
    )
    board = json.loads(db.get_job(job_id)["storyboard_json"])

    filtresiz = variation_guard.evaluate(
        channel="bedtime",
        script=p.narration_text,
        storyboard=board,
        title="Fen and the Lost Feather",
        asset_ids=storyboard.variation_asset_ids(board),
        voice_id="af_bella",
        fmt=None,
    )

    assert not filtresiz.passed


def test_serit_kapiyi_gevsetmiyor(tmp_path):
    """Format şeridi bir muafiyet değil. İki neredeyse aynı Short hâlâ reddedilir."""
    a = _episode(tmp_path)
    _publish_fingerprint(a, "episode")
    first, p = shorts.create(
        a, narrator=fake_narrator(38.0), renderer=fake_renderer(tmp_path)
    )
    db.update_job(first, status=db.JobStatus.PUBLISHED.value)
    _publish_fingerprint(first, "short")

    board = json.loads(db.get_job(first)["storyboard_json"])
    verdict = variation_guard.evaluate(
        channel="bedtime",
        script=p.narration_text,
        storyboard=board,
        title=db.get_job(first)["title"] or "",
        asset_ids=storyboard.variation_asset_ids(board),
        voice_id="af_bella",
        fmt="short",
    )

    assert not verdict.passed


def test_parmak_izi_formati_tasir(tmp_path):
    parent = _episode(tmp_path)
    _publish_fingerprint(parent, "episode")

    assert db.recent_fingerprints("bedtime", fmt="episode")
    assert db.recent_fingerprints("bedtime", fmt="short") == []


def test_recent_jobs_formata_gore_filtreler(tmp_path):
    _episode(tmp_path)
    assert len(db.recent_jobs("bedtime", fmt="episode")) == 1
    assert db.recent_jobs("bedtime", fmt="short") == []


# --------------------------------------------------------------------------
# Derleme
# --------------------------------------------------------------------------

def test_derleme_hedef_sureye_kadar_bolum_toplar(tmp_path):
    for i in range(6):
        _episode(tmp_path, title=f"Episode {i}", duration=600, day_offset=i)

    plan = compilation.select(config.Channel.BEDTIME)

    assert plan.total_seconds >= 2400
    assert len(plan.members) == 5  # 5 x 600 = 3000 = hedef


def test_yetersiz_malzemede_net_hata(tmp_path):
    _episode(tmp_path, duration=600)

    with pytest.raises(compilation.CompilationError, match="Yeterli yayınlanmış bölüm yok"):
        compilation.select(config.Channel.BEDTIME)


def test_dosyasi_silinmis_bolum_atlanir(tmp_path):
    for i in range(5):
        _episode(tmp_path, title=f"Episode {i}", duration=600, day_offset=i)
    kayip = _episode(tmp_path, title="Kayıp", duration=600, with_file=False, day_offset=9)

    plan = compilation.select(config.Channel.BEDTIME)

    assert kayip not in plan.member_ids


def test_derleme_uyeleri_kaydedilir(tmp_path):
    for i in range(5):
        _episode(tmp_path, title=f"Episode {i}", duration=600, day_offset=i)

    job_id, plan = compilation.build(
        config.Channel.BEDTIME, concat=lambda paths, out: out
    )

    row = db.get_job(job_id)
    assert row["format"] == "compilation"
    board = json.loads(row["storyboard_json"])
    assert board["compilation"]["members"] == plan.member_ids
    assert len(board["scenes"]) == len(plan.members)


def test_ayni_bolumlerden_ikinci_derleme_reddedilir(tmp_path):
    """Aynı bölümleri farklı sırayla yeniden yayınlamak, tekrar sinyalinin
    en çıplak hâli."""
    for i in range(5):
        _episode(tmp_path, title=f"Episode {i}", duration=600, day_offset=i)

    first, _ = compilation.build(config.Channel.BEDTIME, concat=lambda paths, out: out)
    db.update_job(first, status=db.JobStatus.PUBLISHED.value)

    with pytest.raises(compilation.CompilationError, match="örtüşüyor"):
        compilation.build(config.Channel.BEDTIME, concat=lambda paths, out: out)


def test_birlestirme_hatasi_isi_failed_yapar(tmp_path):
    for i in range(5):
        _episode(tmp_path, title=f"Episode {i}", duration=600, day_offset=i)

    def broken(paths, out):
        raise RuntimeError("ffmpeg çöktü")

    with pytest.raises(compilation.CompilationError, match="Birleştirme başarısız"):
        compilation.build(config.Channel.BEDTIME, concat=broken)

    assert db.jobs_by_status(db.JobStatus.FAILED)


def test_derleme_yayin_sirasini_korur(tmp_path):
    """Palet bölüm sonuna doğru koyulaşıyor; rastgele sıra tonu tersine çevirir."""
    ids = [
        _episode(tmp_path, title=f"Episode {i}", duration=600, day_offset=i)
        for i in range(5)
    ]

    plan = compilation.select(config.Channel.BEDTIME)

    assert plan.member_ids == ids[: len(plan.members)]


# --------------------------------------------------------------------------
# Diller arası: Shorts boyutları
# --------------------------------------------------------------------------

def test_shorts_boyutlari_remotion_ile_ayni():
    """Uyumsuzluk render'ı bozmaz — sessizce yanlış oranda video üretir ve
    YouTube onu Shorts rafına koymaz."""
    root = (config.REPO_ROOT / "remotion" / "src" / "Root.tsx").read_text(encoding="utf-8")

    w = re.search(r"const SHORT_WIDTH = (\d+)", root)
    h = re.search(r"const SHORT_HEIGHT = (\d+)", root)
    assert w and h, "Root.tsx içinde Shorts boyutları bulunamadı"

    assert (int(w.group(1)), int(h.group(1))) == (
        config.SHORTS_WIDTH,
        config.SHORTS_HEIGHT,
    )


def test_short_kompozisyonu_tanimli():
    from core import render

    root = (config.REPO_ROOT / "remotion" / "src" / "Root.tsx").read_text(encoding="utf-8")

    assert f'id="{render.SHORT_COMPOSITION_ID}"' in root
    assert f'id="{render.COMPOSITION_ID}"' in root
