"""Uçtan uca hat testleri — API çağrısı, TTS veya render çalıştırmadan.

Kanıtlanan asıl şey: aşamalar doğru SIRADA çalışıyor ve düşen kapı hattı
durduruyor. Özellikle varyasyon kapısı render'dan ÖNCE — bu makinede
reddedilecek bir videoyu render etmek ~23 dakika harcamak olurdu.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core import approval, budget, config, db, ideation, narration, pipeline, script


@pytest.fixture(autouse=True)
def temp_output(tmp_path, monkeypatch):
    for name in ("PENDING_DIR", "APPROVED_DIR", "REJECTED_DIR"):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(config, name, d)


def fake_generator(text: str | None = None, scenes: int = 8, title: str | None = None):
    """Deterministik sahte senaryo üreteci — API çağırmaz, para harcamaz."""

    def _gen(job_id: int, premise: ideation.Premise, fmt: str) -> script.ScriptResult:
        body = text or f"A story about {premise.character} in the {premise.setting}. " * 40
        per_scene = body[: max(1, len(body) // scenes)]
        episode = script.Episode(
            title=title or f"{premise.character.title()} and the {premise.topic[:20]}",
            description="A gentle bedtime story.",
            scenes=[
                script.Scene(
                    narration=per_scene,
                    setting=premise.setting,
                    action="walks slowly and looks around",
                    mood=["calm", "curious", "warm", "gentle", "resolved"][i % 5],
                    duration_seconds=60 + i * 7,
                    transition=["fade", "cut", "dissolve", "wipe"][i % 4],
                )
                for i in range(scenes)
            ],
        )
        return script.ScriptResult(
            episode=episode, cost_usd=0.18, rewrites=0, estimated_duration=600.0
        )

    return _gen


def fake_narrator(voice_id: str = "af_bella"):
    """Sahte seslendirici — Kokoro çalıştırmaz, diske yazmaz.

    Gerçek seslendirme her testte saniyeler sürer ve TTS modelini zorunlu
    kılardı; testler donanımdan bağımsız kalmalı.
    """

    def _narrate(job_id: int, storyboard: dict, channel: config.Channel):
        scenes = []
        total = 0.0
        for s in storyboard.get("scenes", []):
            total += float(s.get("duration_seconds", 60))
            scenes.append(
                {**s, "audioSrc": f"scene_{s['index']}.wav", "audioDelaySeconds": 1.2}
            )
        return narration.NarrationResult(
            storyboard={**storyboard, "scenes": scenes},
            audio_dir=config.CACHE_DIR / "tts" / f"job_{job_id}",
            voice_id=voice_id,
            total_seconds=total,
            scene_count=len(scenes),
        )

    return _narrate


def fake_renderer(job_id: int) -> Path:
    return Path(f"D:/otomasyon-data/output/job_{job_id}.mp4")


def _run(**kw):
    """Tüm dış bağımlılıkları sahteyle değiştirerek hattı çalıştırır."""
    kw.setdefault("generator", fake_generator())
    kw.setdefault("narrator", fake_narrator())
    kw.setdefault("renderer", fake_renderer)
    return pipeline.run(**kw)


def _publish(results: list[pipeline.StageResult], voice_id: str = "af_bella") -> int:
    """Bir işi yayınlanmış say ve parmak izini geçmişe yaz."""
    from core import storyboard, variation_guard

    job_id = next(r.job_id for r in results if r.stage == "senaryo")
    db.update_job(job_id, status=db.JobStatus.PUBLISHED.value)
    row = db.get_job(job_id)
    board = json.loads(row["storyboard_json"])
    variation_guard.commit_fingerprint(
        job_id, "bedtime", board, row["title"],
        storyboard.variation_asset_ids(board), voice_id,
    )
    return job_id


# --------------------------------------------------------------------------
# Mutlu yol
# --------------------------------------------------------------------------

def test_asamalar_dogru_sirada_calisir():
    results = _run()

    assert [r.stage for r in results] == [
        "kadans", "senaryo", "seslendirme", "varyasyon", "render", "onay",
    ]
    assert all(r.ok for r in results), pipeline.summary(results)


def test_seslendirme_varyasyondan_once_calisir():
    """Kapının ses ekseni, ses seçilmeden değerlendirilemez."""
    stages = [r.stage for r in _run()]
    assert stages.index("seslendirme") < stages.index("varyasyon")


def test_varyasyon_renderdan_once_calisir():
    stages = [r.stage for r in _run()]
    assert stages.index("varyasyon") < stages.index("render")


def test_render_sonrasi_onay_kuyruguna_duser():
    results = _run()
    job_id = results[-1].job_id

    assert db.get_job(job_id)["status"] == db.JobStatus.AWAITING_APPROVAL.value
    with pytest.raises(approval.ApprovalRequired):
        approval.assert_publishable(job_id)


def test_secilen_ses_ise_kaydedilir():
    _run(narrator=fake_narrator(voice_id="bf_emma"))
    job = db.jobs_by_status(db.JobStatus.AWAITING_APPROVAL)[0]
    assert job["voice_id"] == "bf_emma"


def test_seslendirme_sahne_sureleri_isi_gunceller():
    """Süre, senaryo tahmini değil seslendirme sonucu olmalı."""
    results = _run()
    job = db.get_job(results[-1].job_id)

    board = json.loads(job["storyboard_json"])
    assert all(s.get("audioSrc") for s in board["scenes"])
    assert job["duration_seconds"] == sum(s["duration_seconds"] for s in board["scenes"])


# --------------------------------------------------------------------------
# Kapılar
# --------------------------------------------------------------------------

def test_ayni_senaryo_ikinci_kez_varyasyon_kapisinda_durur():
    """KRİTİK: hat, kopya içeriği render'a geçirmemeli."""
    sabit = "The same story told the exact same way every single time it runs. " * 40
    gen = fake_generator(text=sabit)

    _publish(_run(generator=gen))
    ikinci = _run(generator=gen)

    varyasyon = next(r for r in ikinci if r.stage == "varyasyon")
    assert not varyasyon.ok
    assert "senaryo" in varyasyon.detail
    # Render aşamasına HİÇ ulaşılmamalı — asıl kazanç bu.
    assert "render" not in {r.stage for r in ikinci}


def test_reddedilen_is_silinmez():
    sabit = "Identical narration content repeated for the duplicate detection test. " * 40
    gen = fake_generator(text=sabit)

    _publish(_run(generator=gen))
    ikinci = _run(generator=gen)
    reddedilen = next(r for r in ikinci if r.stage == "varyasyon").job_id

    row = db.get_job(reddedilen)
    assert row is not None
    assert row["status"] == db.JobStatus.REJECTED.value
    assert row["attempt"] == 2


def test_gunluk_tavan_dolunca_hat_baslamaz():
    from datetime import UTC, datetime

    today = datetime.now(UTC).isoformat()
    for _ in range(config.HARD_DAILY_CAP_LONGFORM):
        j = db.create_job("bedtime", "episode")
        db.update_job(j, status=db.JobStatus.PUBLISHED.value, published_at=today)

    results = _run()

    assert len(results) == 1
    assert results[0].stage == "kadans"
    assert not results[0].ok
    assert "tavan" in results[0].detail


def test_butce_asiminda_hat_durur():
    def broke(job_id, premise, fmt):
        raise budget.BudgetExceeded("Aylık tavan aşıldı.")

    results = _run(generator=broke)

    senaryo = next(r for r in results if r.stage == "senaryo")
    assert not senaryo.ok
    assert "BÜTÇE" in senaryo.detail
    assert db.get_job(senaryo.job_id)["status"] == db.JobStatus.FAILED.value


def test_seslendirme_hatasi_hatti_durdurur():
    def broken(job_id, storyboard, channel):
        raise RuntimeError("Kokoro modeli yok")

    results = _run(narrator=broken)

    stage = next(r for r in results if r.stage == "seslendirme")
    assert not stage.ok
    assert "Kokoro" in stage.detail
    assert "varyasyon" not in {r.stage for r in results}


def test_render_hatasi_isi_failed_yapar():
    def broken(job_id):
        raise RuntimeError("Remotion çöktü")

    results = _run(renderer=broken)

    stage = next(r for r in results if r.stage == "render")
    assert not stage.ok
    assert db.get_job(stage.job_id)["status"] == db.JobStatus.FAILED.value
    assert "onay" not in {r.stage for r in results}


def test_pasif_kanal_uretim_yapmaz():
    results = _run(channel=config.Channel.STORYTIME)

    kanal = next(r for r in results if r.stage == "kanal")
    assert not kanal.ok
    assert "pasif" in kanal.detail


# --------------------------------------------------------------------------
# Storyboard
# --------------------------------------------------------------------------

def test_storyboard_asset_kimlikleri_turetilir():
    from core import storyboard

    results = _run()
    board = json.loads(db.get_job(results[-1].job_id)["storyboard_json"])

    ids = storyboard.asset_ids(board)

    assert any(i.startswith("bg/") for i in ids)
    assert any(i.startswith("char/") for i in ids)


def test_storyboard_premise_i_korur():
    """ideation geri beslemesi buna bağlı — son bölümlerin eksenleri buradan okunur."""
    results = _run()
    board = json.loads(db.get_job(results[-1].job_id)["storyboard_json"])

    premise = board["premise"]
    assert premise["character"] and premise["setting"] and premise["shape"]
    assert premise["protagonist"] == "Fen"


def test_ruh_hali_arka_plan_varyantini_degistirir():
    from core import storyboard

    a = storyboard._background_id("quiet forest", "calm")
    b = storyboard._background_id("quiet forest", "warm")
    assert a != b
    assert a.startswith("bg/quiet_forest/")


def test_eylem_karakter_pozunu_secer():
    from core import storyboard

    assert storyboard._character_id("owl", "walks to the pond").endswith("/walking")
    assert storyboard._character_id("owl", "sits and rests").endswith("/resting")
    assert storyboard._character_id("owl", "looks at the moon").endswith("/looking")
    assert storyboard._character_id("owl", "carries a stone").endswith("/carrying")
