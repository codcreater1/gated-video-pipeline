"""BÜTÇE KAPISI testleri — kapının gerçekten DURDURDUĞUNU kanıtlar."""

from __future__ import annotations

import pytest

from core import budget, config, db


def _job() -> int:
    return db.create_job("bedtime", "episode", topic="test")


def test_ucretsiz_islem_gecer():
    job = _job()
    assert budget.check(job, 0.0)


def test_normal_harcama_gecer():
    job = _job()
    decision = budget.check(job, 1.00)
    assert decision.allowed
    assert decision.job_remaining_usd == pytest.approx(config.BUDGET_MAX_USD_PER_VIDEO)


def test_video_tavani_asilinca_reddeder():
    """Tavan $4.00. $3.50 harcanmışken $1.00 daha istenirse reddedilmeli."""
    job = _job()
    budget.commit(job, "ai_video", 3.50, "3 klip")

    decision = budget.check(job, 1.00)

    assert not decision.allowed
    assert "Video tavanı aşılır" in decision.reason
    assert decision.job_spent_usd == pytest.approx(3.50)


def test_reddedilen_harcama_deftere_yazilmaz():
    job = _job()
    budget.commit(job, "ai_video", 3.90)

    allowed = budget.guard(job, "ai_video", 1.00, "asilmali")

    assert allowed is False
    # Harcama artmadı — reddedilen çağrı para harcamadı
    assert db.job_spend(job) == pytest.approx(3.90)


def test_aylik_tavan_asilinca_uretim_durur():
    """Aylık tavan aşımı BudgetExceeded fırlatır — hat tamamen durur."""
    job = _job()
    db.record_spend(job, "ai_video", config.BUDGET_MAX_USD_PER_MONTH - 0.10, "gecmis")

    with pytest.raises(budget.BudgetExceeded, match="Aylık tavan"):
        budget.guard(job, "ai_video", 5.00)


def test_ai_klip_maliyeti_yukari_yuvarlar():
    """Kling 10 saniyelik dilimlerle faturalandırır."""
    assert budget.ai_clip_cost(10) == pytest.approx(config.KLING_USD_PER_10S)
    assert budget.ai_clip_cost(11) == pytest.approx(config.KLING_USD_PER_10S * 2)
    assert budget.ai_clip_cost(1) == pytest.approx(config.KLING_USD_PER_10S)


def test_ai_video_on_denetimi_rejenerasyonu_hesaba_katar():
    """En kötü senaryo: her klip MAX_REGENERATIONS_PER_CLIP kez yeniden üretilir.

    4 klip x 3 deneme x $0.84 = $10.08 — $4.00 tavanının çok üstünde, reddedilmeli.
    Bu tam olarak '5. rejenerasyonda $1.50'lik klip $5 olur' tuzağını önleyen denetim.
    """
    job = _job()
    decision = budget.can_afford_ai_video(job, clip_count=4, seconds_each=10)
    assert not decision.allowed


def test_ai_video_on_denetimi_kucuk_iste_gecer():
    job = _job()
    decision = budget.can_afford_ai_video(job, clip_count=1, seconds_each=10)
    # 1 klip x 3 deneme x $0.84 = $2.52 < $4.00
    assert decision.allowed


def test_klip_sayisi_ust_sinira_kirpilir():
    job = _job()
    çok = budget.can_afford_ai_video(job, clip_count=99, seconds_each=10)
    sinirda = budget.can_afford_ai_video(job, clip_count=config.MAX_AI_CLIPS_PER_VIDEO)
    assert çok.allowed == sinirda.allowed
