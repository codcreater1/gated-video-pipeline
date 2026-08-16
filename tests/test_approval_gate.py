"""ONAY KAPISI testleri — onaylanmamış videonun yayınlanamadığını kanıtlar."""

from __future__ import annotations

import json

import pytest

from core import approval, config, db


@pytest.fixture(autouse=True)
def temp_output(tmp_path, monkeypatch):
    """Onay kuyruğu dizinlerini geçici dizine yönlendirir."""
    for name in ("PENDING_DIR", "APPROVED_DIR", "REJECTED_DIR"):
        d = tmp_path / name.lower()
        d.mkdir()
        monkeypatch.setattr(config, name, d)


def _rendered_job() -> int:
    job = db.create_job("bedtime", "episode", topic="Luna ve ay")
    db.update_job(
        job,
        title="Luna and the Sleepy Moon",
        script="Luna the little owl could not sleep. " * 30,
        storyboard_json=json.dumps({"scenes": [{"duration_seconds": 60}] * 8}),
        duration_seconds=600,
        output_path="D:/otomasyon-data/output/job.mp4",
        cost_usd=2.40,
        status=db.JobStatus.RENDERING.value,
    )
    return job


def test_submit_inceleme_karti_yazar():
    job = _rendered_job()
    card = approval.submit(job)

    assert card.title == "Luna and the Sleepy Moon"
    assert card.scene_count == 8
    assert card.made_for_kids is True
    assert len(card.checklist) == 5
    assert (config.PENDING_DIR / f"job_{job}.json").exists()
    assert db.get_job(job)["status"] == db.JobStatus.AWAITING_APPROVAL.value


def test_onaylanmamis_video_yayinlanamaz():
    """KRİTİK TEST: onay kapısının asıl işi."""
    job = _rendered_job()
    approval.submit(job)

    with pytest.raises(approval.ApprovalRequired, match="onaylanmamış"):
        approval.assert_publishable(job)


def test_render_edilmis_ama_gonderilmemis_is_yayinlanamaz():
    job = _rendered_job()
    with pytest.raises(approval.ApprovalRequired):
        approval.assert_publishable(job)


def test_onaylanan_video_yayinlanabilir():
    job = _rendered_job()
    approval.submit(job)
    approval.approve(job, reviewer="test")

    approval.assert_publishable(job)  # fırlatmamalı

    assert db.get_job(job)["status"] == db.JobStatus.APPROVED.value
    assert (config.APPROVED_DIR / f"job_{job}.json").exists()
    assert not (config.PENDING_DIR / f"job_{job}.json").exists()


def test_onay_kaydi_reviewer_ve_zaman_tutar():
    job = _rendered_job()
    approval.submit(job)
    approval.approve(job, reviewer="stere")

    data = json.loads((config.APPROVED_DIR / f"job_{job}.json").read_text(encoding="utf-8"))
    assert data["approved_by"] == "stere"
    assert data["approved_at"]


def test_insan_reddi_isi_silmez():
    job = _rendered_job()
    approval.submit(job)
    approval.reject(job, "Hikâye yayı zayıf, 3. sahne boş geçiyor")

    row = db.get_job(job)
    assert row is not None
    assert row["status"] == db.JobStatus.REJECTED.value
    assert row["attempt"] == 2
    assert "ONAY:" in row["rejection_reason"]
    assert (config.REJECTED_DIR / f"job_{job}.json").exists()


def test_ayni_isi_iki_kez_onaylamak_hata_verir():
    job = _rendered_job()
    approval.submit(job)
    approval.approve(job)

    with pytest.raises(approval.ApprovalRequired, match="onay bekleme durumunda değil"):
        approval.approve(job)


def test_bekleyen_kuyrugu_listelenir():
    j1, j2 = _rendered_job(), _rendered_job()
    approval.submit(j1)
    approval.submit(j2)
    approval.approve(j1)

    bekleyen = approval.pending()

    assert [c["job_id"] for c in bekleyen] == [j2]


def test_kapi_kapaliysa_engellenmez_ama_bu_yapilandirma_sorunu():
    """REQUIRE_HUMAN_APPROVAL=false teknik olarak çalışır ama validate() bunu raporlar."""
    job = _rendered_job()

    original = config.REQUIRE_HUMAN_APPROVAL
    try:
        config.REQUIRE_HUMAN_APPROVAL = False
        approval.assert_publishable(job)  # fırlatmıyor
        assert any("REQUIRE_HUMAN_APPROVAL" in p for p in config.validate())
    finally:
        config.REQUIRE_HUMAN_APPROVAL = original
