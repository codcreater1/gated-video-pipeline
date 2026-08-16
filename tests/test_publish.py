"""Yayın testleri — Google API'sine hiç dokunmadan.

Kanıtlanan asıl şey: yükleme geri alınamaz bir işlem ve ondan önceki her
denetim gerçekten çalışıyor. Onaysız bir işin, tavanı aşan bir günün veya
yanlış Made for Kids bayrağının API'ye ulaşamadığı burada gösteriliyor.
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import pytest
from test_pipeline import fake_generator, fake_narrator

from core import approval, config, db, publish, storyboard, variation_guard


@pytest.fixture(autouse=True)
def temp_dirs(tmp_path, monkeypatch):
    for name in ("PENDING_DIR", "APPROVED_DIR", "REJECTED_DIR", "PUBLISHED_DIR",
                 "CREDENTIALS_DIR", "OUTPUT_DIR"):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(config, name, d)


class FakeUploader:
    """Yüklemeyi taklit eder ve gönderilen meta veriyi saklar.

    Testlerin çoğu "ne yüklendi" değil "ne gönderildi" ile ilgileniyor —
    Made for Kids bayrağı gibi kritik alanlar gövdede doğrulanmalı.
    """

    def __init__(self, video_id: str = "abc123XYZ_0"):
        self.video_id = video_id
        self.calls: list[dict] = []

    def __call__(self, channel, video_path: Path, metadata: dict) -> str:
        self.calls.append(
            {"channel": channel, "video_path": video_path, "metadata": metadata}
        )
        return self.video_id

    @property
    def metadata(self) -> dict:
        assert self.calls, "Yükleyici hiç çağrılmadı"
        return self.calls[-1]["metadata"]


def _approved_job(tmp_path: Path, reviewer: str = "human") -> int:
    """Onay kuyruğundan geçmiş, dosyası diskte olan bir iş üretir."""
    from core import pipeline

    def renderer(job_id: int) -> Path:
        out = tmp_path / f"job_{job_id}.mp4"
        out.write_bytes(b"\x00" * 1024)
        return out

    results = pipeline.run(
        generator=fake_generator(), narrator=fake_narrator(), renderer=renderer
    )
    assert all(r.ok for r in results), pipeline.summary(results)

    job_id = results[-1].job_id
    approval.approve(job_id, reviewer=reviewer)
    return job_id


# --------------------------------------------------------------------------
# Onay kapısı
# --------------------------------------------------------------------------

def test_onaysiz_is_yayinlanamaz(tmp_path):
    """KRİTİK: onay kapısı yayının önünde durmalı, yoksa hattın anlamı kalmıyor."""
    from core import pipeline

    def renderer(job_id: int) -> Path:
        out = tmp_path / f"job_{job_id}.mp4"
        out.write_bytes(b"\x00" * 1024)
        return out

    results = pipeline.run(
        generator=fake_generator(), narrator=fake_narrator(), renderer=renderer
    )
    job_id = results[-1].job_id  # AWAITING_APPROVAL — approve() çağrılmadı
    up = FakeUploader()

    with pytest.raises(approval.ApprovalRequired):
        publish.publish(job_id, uploader=up)

    assert not up.calls, "Onaysız iş için yükleyici çağrılmış"


def test_onayli_is_yayinlanir(tmp_path):
    job_id = _approved_job(tmp_path)
    up = FakeUploader(video_id="dQw4w9WgXcQ")

    result = publish.publish(job_id, uploader=up)

    assert result.youtube_video_id == "dQw4w9WgXcQ"
    assert result.url == "https://www.youtube.com/watch?v=dQw4w9WgXcQ"

    row = db.get_job(job_id)
    assert row["status"] == db.JobStatus.PUBLISHED.value
    assert row["youtube_video_id"] == "dQw4w9WgXcQ"
    assert row["published_at"]


def test_ayni_is_ikinci_kez_yuklenmez(tmp_path):
    """Çift yükleme kanalda doğrudan tekrar sinyali üretir."""
    job_id = _approved_job(tmp_path)
    publish.publish(job_id, uploader=FakeUploader())

    ikinci = FakeUploader()
    with pytest.raises(publish.PublishError, match="zaten yayınlanmış"):
        publish.publish(job_id, uploader=ikinci)

    assert not ikinci.calls


# --------------------------------------------------------------------------
# Made for Kids — FTC/COPPA
# --------------------------------------------------------------------------

def test_mfk_bayragi_api_govdesine_dogru_gider(tmp_path):
    """Yazılabilir alan selfDeclaredMadeForKids; madeForKids salt okunur.

    Yanlış alanı göndermek bayrağı sessizce ayarlanmamış bırakırdı.
    """
    job_id = _approved_job(tmp_path)
    up = FakeUploader()

    publish.publish(job_id, uploader=up)

    assert up.metadata["status"]["selfDeclaredMadeForKids"] is True
    assert "madeForKids" not in up.metadata["status"]


def test_yanlis_siniflandirma_yuklemeyi_durdurur(tmp_path, monkeypatch):
    """Biri RPM için bayrağı çevirirse API çağrısı HİÇ yapılmamalı."""
    job_id = _approved_job(tmp_path)

    bozuk = dataclasses.replace(
        config.CHANNELS[config.Channel.BEDTIME], made_for_kids=False
    )
    monkeypatch.setitem(config.CHANNELS, config.Channel.BEDTIME, bozuk)

    up = FakeUploader()
    with pytest.raises(publish.MisclassificationError, match="COPPA"):
        publish.publish(job_id, uploader=up)

    assert not up.calls
    assert db.get_job(job_id)["status"] == db.JobStatus.APPROVED.value


# --------------------------------------------------------------------------
# Günlük tavan
# --------------------------------------------------------------------------

def test_gunluk_tavan_yayin_aninda_denetlenir(tmp_path):
    """Üretim tavanı işi kuyruğa almayı engelliyor; asıl tavan YAYINDA.

    Onaylı işler birikir. Beş onaylı videoyu aynı gün yayınlamak, üretim
    tarafındaki denetimi tamamen boşa çıkarırdı.
    """
    from datetime import UTC, datetime

    # Sıra gerçek senaryoyu izliyor: iş önce onaylanır (kuyrukta bekler),
    # tavan sonra dolar. Tersi zaten üretim tarafındaki kapıya takılırdı.
    job_id = _approved_job(tmp_path)

    today = datetime.now(UTC).isoformat()
    for _ in range(config.HARD_DAILY_CAP_LONGFORM):
        j = db.create_job("bedtime", "episode")
        db.update_job(j, status=db.JobStatus.PUBLISHED.value, published_at=today)

    up = FakeUploader()

    with pytest.raises(publish.DailyCapReached):
        publish.publish(job_id, uploader=up)

    assert not up.calls
    # İş kaybolmaz — yarın yayınlanabilir.
    assert db.get_job(job_id)["status"] == db.JobStatus.APPROVED.value


# --------------------------------------------------------------------------
# Varyasyon parmak izi
# --------------------------------------------------------------------------

def test_parmak_izi_yayin_aninda_yazilir(tmp_path):
    """Yayınlanmamış denemeler varyasyon penceresini kirletmemeli."""
    job_id = _approved_job(tmp_path)

    assert db.recent_fingerprints("bedtime") == []

    publish.publish(job_id, uploader=FakeUploader())

    fingerprints = db.recent_fingerprints("bedtime")
    assert len(fingerprints) == 1
    assert fingerprints[0]["job_id"] == job_id


def test_parmak_izi_yayinlanan_isin_eksenlerini_tasir(tmp_path):
    job_id = _approved_job(tmp_path)
    row = db.get_job(job_id)
    board = json.loads(row["storyboard_json"])

    publish.publish(job_id, uploader=FakeUploader())

    fp = db.recent_fingerprints("bedtime")[0]
    assert fp["structure_hash"] == variation_guard.structure_hash(board)
    assert fp["title_pattern"] == variation_guard.title_pattern(row["title"])
    assert json.loads(fp["asset_ids_json"]) == storyboard.variation_asset_ids(board)
    assert fp["voice_id"] == row["voice_id"]


# --------------------------------------------------------------------------
# Dosya ve arşiv
# --------------------------------------------------------------------------

def test_video_dosyasi_yoksa_yukleme_yapilmaz(tmp_path):
    job_id = _approved_job(tmp_path)
    Path(db.get_job(job_id)["output_path"]).unlink()

    up = FakeUploader()
    with pytest.raises(publish.PublishError, match="Video dosyası yok"):
        publish.publish(job_id, uploader=up)

    assert not up.calls


def test_yukleme_koparsa_is_onayli_kalir(tmp_path):
    """Yeniden denenebilmeli — kopan yükleme işi kaybettirmemeli."""

    def broken(channel, video_path, metadata):
        raise publish.PublishError("YouTube 503: geçici hata")

    job_id = _approved_job(tmp_path)

    with pytest.raises(publish.PublishError):
        publish.publish(job_id, uploader=broken)

    row = db.get_job(job_id)
    assert row["status"] == db.JobStatus.APPROVED.value
    assert not row["youtube_video_id"]


def test_onay_karti_yayinlanmis_arsivine_tasinir(tmp_path):
    """Kanal politika incelemesine girerse onay kaydı tek kanıt."""
    job_id = _approved_job(tmp_path, reviewer="stere")
    assert (config.APPROVED_DIR / f"job_{job_id}.json").exists()

    result = publish.publish(job_id, uploader=FakeUploader())

    assert not (config.APPROVED_DIR / f"job_{job_id}.json").exists()
    archived = config.PUBLISHED_DIR / f"job_{job_id}.json"
    assert archived.exists()

    data = json.loads(archived.read_text(encoding="utf-8"))
    assert data["approved_by"] == "stere"
    assert data["youtube_video_id"] == result.youtube_video_id
    assert data["published_at"]


def test_yukleme_bekleyenler_listelenir(tmp_path):
    job_id = _approved_job(tmp_path)
    assert [j["id"] for j in publish.pending_uploads()] == [job_id]

    publish.publish(job_id, uploader=FakeUploader())
    assert publish.pending_uploads() == []


# --------------------------------------------------------------------------
# Meta veri
# --------------------------------------------------------------------------

def test_auto_dubbing_icin_ses_dili_dolu(tmp_path):
    """defaultAudioLanguage boşsa YouTube auto-dubbing hiç çalışmıyor —
    kanalın 27 dile açılma planı sessizce iptal olurdu."""
    job_id = _approved_job(tmp_path)
    up = FakeUploader()

    publish.publish(job_id, uploader=up)

    assert up.metadata["snippet"]["defaultAudioLanguage"] == "en"


def test_baslik_100_karakteri_asmaz(tmp_path):
    """YouTube başlığı 100 karakterde kesiyor; kesmeyi biz kontrol etmeliyiz."""
    job_id = _approved_job(tmp_path)
    db.update_job(job_id, title="Ç" * 250)

    up = FakeUploader()
    publish.publish(job_id, uploader=up)

    assert len(up.metadata["snippet"]["title"]) == 100


def test_gizlilik_durumu_gecirilir(tmp_path):
    job_id = _approved_job(tmp_path)
    up = FakeUploader()

    result = publish.publish(job_id, uploader=up, privacy_status="unlisted")

    assert up.metadata["status"]["privacyStatus"] == "unlisted"
    assert result.privacy_status == "unlisted"


# --------------------------------------------------------------------------
# Token yolu
# --------------------------------------------------------------------------

def test_token_varsayilan_olarak_repo_disinda():
    """Token repo içinde yaşarsa er ya da geç commit'lenir."""
    path = publish.token_path(config.Channel.BEDTIME)

    assert path.parent == config.CREDENTIALS_DIR
    assert config.REPO_ROOT not in path.parents


def test_env_degiskeni_token_yolunu_ezer(monkeypatch, tmp_path):
    hedef = tmp_path / "ozel_token.json"
    monkeypatch.setenv("YT_CHANNEL_A_TOKEN_FILE", str(hedef))

    assert publish.token_path(config.Channel.BEDTIME) == hedef


def test_yetkilendirilmemis_kanal_net_hata_verir(monkeypatch):
    """Token denetimi google import'larından ÖNCE olmalı.

    Aksi halde [runtime] extra'sı kurulu olmayan bir ortamda kullanıcı, asıl
    sorunu (yetkilendirme yok) değil ham bir ModuleNotFoundError görürdü.
    """
    monkeypatch.delenv("YT_CHANNEL_A_TOKEN_FILE", raising=False)
    assert not publish.authorized(config.Channel.BEDTIME)

    with pytest.raises(publish.NotAuthorized, match="authorize bedtime"):
        publish._service(config.Channel.BEDTIME)


def test_google_istemcisi_yoksa_net_hata_verir(monkeypatch):
    """[runtime] extra'sı kurulmadan yayın denenirse ne kurulacağı söylenmeli."""
    import importlib.util

    monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

    with pytest.raises(publish.PublishError, match=r'\[runtime\]'):
        publish._require_google()
