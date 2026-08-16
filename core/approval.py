"""ONAY KAPISI — üçüncü ve son kapı.

Otomasyon üretimi yapar; yayın kararını insan verir. Bu kapı `REQUIRE_HUMAN_APPROVAL`
false yapılmadıkça bypass edilemez ve `config.validate()` bunu bir sorun olarak raporlar.

Neden: inauthentic content politikasının merkezinde "her video izleyiciye yaratıcı,
eğitici veya başka bir değer sunuyor mu" sorusu var. Bunu otomatik denetleyemeyiz.
Varyasyon kapısı tekrarı yakalar; değeri yakalayamaz. O yüzden insan gerekli.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from core import config, db

# docs/content-guidelines.md §6 — onay kapısında sorulan asgari değer testi.
# Biri bile "hayır" ise video yayınlanmaz.
VALUE_CHECKLIST = [
    "Bu bölümün kendine ait bir hikâyesi var mı (başka bölümün yeniden düzenlemesi değil)?",
    "Karakterler bu bölümde bir şey yapıyor mu, sadece sahne mi değiştiriyor?",
    "Bir çocuk bunu izledikten sonra anlatabileceği bir şey kalıyor mu?",
    "Görseller anlatıyı taşıyor mu, yoksa arka plan döşemesi mi?",
    "Bu videoyu son 10 bölümden ayıran şeyi tek cümleyle söyleyebiliyor muyum?",
]


class ApprovalRequired(Exception):
    """Onaylanmamış iş yayınlanmaya çalışıldı."""


@dataclass
class ReviewCard:
    """İnsanın karar vermek için görmesi gereken her şey, tek yerde."""

    job_id: int
    channel: str
    fmt: str
    title: str
    topic: str
    duration_seconds: int
    cost_usd: float
    video_path: str
    made_for_kids: bool
    script_excerpt: str
    scene_count: int
    variation_notes: list[str] = field(default_factory=list)
    checklist: list[str] = field(default_factory=lambda: list(VALUE_CHECKLIST))

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "channel": self.channel,
            "format": self.fmt,
            "title": self.title,
            "topic": self.topic,
            "duration_seconds": self.duration_seconds,
            "duration_human": f"{self.duration_seconds // 60}dk {self.duration_seconds % 60}sn",
            "cost_usd": round(self.cost_usd, 2),
            "video_path": self.video_path,
            "made_for_kids": self.made_for_kids,
            "scene_count": self.scene_count,
            "script_excerpt": self.script_excerpt,
            "variation_notes": self.variation_notes,
            "checklist": self.checklist,
        }


def _card_path(job_id: int) -> Path:
    return config.PENDING_DIR / f"job_{job_id}.json"


def submit(job_id: int, variation_notes: list[str] | None = None) -> ReviewCard:
    """Render'ı biten işi onay kuyruğuna alır ve inceleme kartı yazar."""
    job = db.get_job(job_id)
    if job is None:
        raise ValueError(f"İş bulunamadı: {job_id}")

    profile = config.CHANNELS[config.Channel(job["channel"])]
    storyboard = json.loads(job["storyboard_json"] or "{}")
    script = job["script"] or ""

    card = ReviewCard(
        job_id=job_id,
        channel=job["channel"],
        fmt=job["format"],
        title=job["title"] or "(başlık yok)",
        topic=job["topic"] or "",
        duration_seconds=job["duration_seconds"] or 0,
        cost_usd=job["cost_usd"] or 0.0,
        video_path=job["output_path"] or "",
        made_for_kids=profile.made_for_kids,
        script_excerpt=script[:600] + ("…" if len(script) > 600 else ""),
        scene_count=len(storyboard.get("scenes", [])),
        variation_notes=variation_notes or [],
    )

    config.PENDING_DIR.mkdir(parents=True, exist_ok=True)
    _card_path(job_id).write_text(
        json.dumps(card.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    db.update_job(job_id, status=db.JobStatus.AWAITING_APPROVAL.value)
    return card


def pending() -> list[dict[str, Any]]:
    """Onay bekleyen işlerin inceleme kartları."""
    cards = []
    for job in db.jobs_by_status(db.JobStatus.AWAITING_APPROVAL):
        path = _card_path(job["id"])
        if path.exists():
            cards.append(json.loads(path.read_text(encoding="utf-8")))
        else:
            cards.append({"job_id": job["id"], "title": job["title"], "card": "eksik"})
    return cards


def approve(job_id: int, reviewer: str = "human") -> None:
    """İşi onaylar ve yükleme kuyruğuna taşır."""
    job = db.get_job(job_id)
    if job is None:
        raise ValueError(f"İş bulunamadı: {job_id}")
    if job["status"] != db.JobStatus.AWAITING_APPROVAL.value:
        raise ApprovalRequired(
            f"İş #{job_id} onay bekleme durumunda değil (şu an: {job['status']})."
        )

    card = _card_path(job_id)
    if card.exists():
        config.APPROVED_DIR.mkdir(parents=True, exist_ok=True)
        target = config.APPROVED_DIR / card.name
        data = json.loads(card.read_text(encoding="utf-8"))
        data["approved_by"] = reviewer
        data["approved_at"] = datetime.now(UTC).isoformat()
        target.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        card.unlink()

    db.update_job(job_id, status=db.JobStatus.APPROVED.value)


def reject(job_id: int, reason: str) -> None:
    """İnsan reddetti. İş silinmez — yeniden üretim kuyruğuna düşer."""
    card = _card_path(job_id)
    if card.exists():
        config.REJECTED_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(card), str(config.REJECTED_DIR / card.name))
    db.reject_job(job_id, f"ONAY: {reason}")


def assert_publishable(job_id: int) -> None:
    """Yükleme öncesi son kontrol. publish.py bunu ÇAĞIRMAK ZORUNDA.

    Onay kapısı kapalıysa bile burada bir uyarı kaydı bırakılır.
    """
    job = db.get_job(job_id)
    if job is None:
        raise ValueError(f"İş bulunamadı: {job_id}")

    if not config.REQUIRE_HUMAN_APPROVAL:
        # Kapı kapalı — engellemiyoruz ama sessizce de geçmiyoruz.
        return

    if job["status"] != db.JobStatus.APPROVED.value:
        raise ApprovalRequired(
            f"İş #{job_id} onaylanmamış (durum: {job['status']}). "
            f"Yayınlanamaz. Önce `otomasyon approve {job_id}` çalıştır."
        )
