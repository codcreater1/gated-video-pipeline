"""BÜTÇE KAPISI — video başı ve aylık harcama tavanı.

Bu kapı bypass edilemez. Ücretli her çağrı önce buradan izin almak zorunda.

Neden sert: Kling 3.0'da 10 saniyelik 1080p klip ~$0.84. Beşinci rejenerasyonda
$1.50'lik bir klip $5 oluyor — 2026'nın en yaygın AI video maliyet tuzağı.
Tavan aşıldığında hat çökmez, AI video adımını atlayıp asset-pack render'a düşer.
"""

from __future__ import annotations

from dataclasses import dataclass

from core import config, db


class BudgetExceeded(Exception):
    """Aylık tavan aşıldı. Üretim tamamen durur."""


@dataclass(frozen=True)
class SpendDecision:
    allowed: bool
    reason: str
    job_spent_usd: float
    job_remaining_usd: float
    month_spent_usd: float
    month_remaining_usd: float

    def __bool__(self) -> bool:
        return self.allowed


def check(job_id: int, projected_usd: float) -> SpendDecision:
    """Planlanan harcamaya izin verilip verilmediğini söyler. Yan etkisi yok.

    Harcamayı KAYDETMEZ — çağıran taraf işlem başarılı olursa `commit()` çağırır.
    """
    job_spent = db.job_spend(job_id)
    month_spent = db.month_spend()

    job_remaining = config.BUDGET_MAX_USD_PER_VIDEO - job_spent
    month_remaining = config.BUDGET_MAX_USD_PER_MONTH - month_spent

    def decide(allowed: bool, reason: str) -> SpendDecision:
        return SpendDecision(
            allowed=allowed,
            reason=reason,
            job_spent_usd=round(job_spent, 4),
            job_remaining_usd=round(job_remaining, 4),
            month_spent_usd=round(month_spent, 4),
            month_remaining_usd=round(month_remaining, 4),
        )

    if projected_usd <= 0:
        return decide(True, "Ücretsiz işlem.")

    if month_spent + projected_usd > config.BUDGET_MAX_USD_PER_MONTH:
        return decide(
            False,
            f"Aylık tavan aşılır: ${month_spent:.2f} + ${projected_usd:.2f} > "
            f"${config.BUDGET_MAX_USD_PER_MONTH:.2f}. Üretim durdu.",
        )

    if job_spent + projected_usd > config.BUDGET_MAX_USD_PER_VIDEO:
        return decide(
            False,
            f"Video tavanı aşılır: ${job_spent:.2f} + ${projected_usd:.2f} > "
            f"${config.BUDGET_MAX_USD_PER_VIDEO:.2f}. AI video atlanıyor, "
            f"asset-pack render'a düşülüyor.",
        )

    return decide(True, f"İzin verildi (${projected_usd:.2f}).")


def commit(job_id: int, category: str, usd: float, detail: str = "") -> None:
    """Gerçekleşmiş harcamayı deftere yazar ve iş toplamını günceller.

    Bu, `check()` izin verdikten VE işlem başarılı olduktan sonra çağrılır.
    Başarısız API çağrısı da para harcatıyorsa yine buraya yazılmalı.
    """
    if usd <= 0:
        return
    db.record_spend(job_id, category, usd, detail)
    db.update_job(job_id, cost_usd=db.job_spend(job_id))


def guard(job_id: int, category: str, usd: float, detail: str = "") -> bool:
    """check + commit birleşimi — harcama kesinse kullanılır.

    True dönerse harcama kaydedildi ve devam edilebilir.
    False dönerse harcama YAPILMAMALI (kaydedilmedi).
    Aylık tavan aşıldıysa BudgetExceeded fırlatır — bu hattın tamamen durması demek.
    """
    decision = check(job_id, usd)
    if not decision.allowed:
        if decision.month_remaining_usd < usd:
            raise BudgetExceeded(decision.reason)
        return False
    commit(job_id, category, usd, detail)
    return True


def ai_clip_cost(seconds: int) -> float:
    """Kling maliyetini 10 saniyelik dilimler üzerinden hesaplar (yukarı yuvarlar)."""
    blocks = max(1, -(-seconds // 10))
    return blocks * config.KLING_USD_PER_10S


def can_afford_ai_video(job_id: int, clip_count: int, seconds_each: int = 10) -> SpendDecision:
    """AI video adımına girmeden önce toplam maliyeti önden denetler.

    Rejenerasyon payı dahil edilir: en kötü senaryoda her klip
    MAX_REGENERATIONS_PER_CLIP kadar yeniden üretilir.
    """
    clip_count = min(clip_count, config.MAX_AI_CLIPS_PER_VIDEO)
    worst_case_attempts = 1 + config.MAX_REGENERATIONS_PER_CLIP
    projected = ai_clip_cost(seconds_each) * clip_count * worst_case_attempts
    return check(job_id, projected)


def summary() -> dict[str, float | str]:
    month_spent = db.month_spend()
    return {
        "month_spent_usd": round(month_spent, 2),
        "month_cap_usd": config.BUDGET_MAX_USD_PER_MONTH,
        "month_remaining_usd": round(config.BUDGET_MAX_USD_PER_MONTH - month_spent, 2),
        "per_video_cap_usd": config.BUDGET_MAX_USD_PER_VIDEO,
    }
