"""Yayın sonrası performans — hattın tek geri besleme döngüsü.

Buraya kadar her şey ileri yönlü: fikir → senaryo → video → yayın. Bu modül
döngüyü kapatır: yayınlanmış bölümlerin retention'ı okunur ve `ideation`'ın
eksen seçimi buna göre ağırlıklandırılır.

**Asıl tasarım kısıtı burada bir gerilim var.** Geri besleme "ne işe yaradıysa
onu daha çok yap" demek ister. Ama bu hattın varlık sebebi tam tersi bir
kısıt: varyasyon kapısı, birbirine benzeyen bölümleri reddediyor. Analytics'i
sınırsız dinlemek, her bölümü en iyi performans gösteren mekân ve misafirle
üretmeye ve varyasyon kapısının hattı kilitlemesine giderdi — üstelik
"şablondan çıkmış içerik" tam olarak inauthentic content politikasının
hedefi. Yani agresif optimizasyon burada kanalı öldüren şey.

O yüzden ağırlıklandırma üç yerden sınırlanmış:

- Bir eksen değeri en az `ANALYTICS_MIN_SAMPLES` bölümde kullanılmadan
  ağırlığı değişmez — tek şanslı video havuzu domine edemez.
- Ağırlık `[ANALYTICS_MIN_WEIGHT, ANALYTICS_MAX_WEIGHT]` aralığına kırpılır.
  En iyi değer nötre göre en fazla iki kat olası; hiçbir değer sıfırlanmaz.
- Yayından `ANALYTICS_MIN_VIDEO_AGE_DAYS` geçmeden ölçüm alınmaz. İlk
  günlerin verisi kanalın performansı değil, bildirim dalgası.

Retention ölçütü views değil **averageViewPercentage**. Views abonelik
sayısıyla ve YouTube'un o günkü dağıtımıyla ölçekleniyor; bir bölümün
kendi başına ne kadar tuttuğunu söylemiyor.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Any

from core import config, db, publish

# ideation'ın ağırlıklandırdığı eksenler. Kahraman burada yok — sabit olması
# tasarım gereği ve ölçmenin bir anlamı olmazdı.
WEIGHTED_AXES = ("setting", "character", "shape")


class AnalyticsError(Exception):
    """Ölçüm alınamadı."""


@dataclass
class VideoStats:
    job_id: int
    youtube_video_id: str
    views: int
    avg_view_duration_s: int
    retention_pct: float

    def summary(self) -> str:
        return (
            f"{self.views} izlenme, {self.avg_view_duration_s}sn ortalama, "
            f"%{self.retention_pct:.1f} tutma"
        )


# --------------------------------------------------------------------------
# Çekme
# --------------------------------------------------------------------------

def _analytics_service(channel: config.Channel):
    """YouTube Analytics API v2 istemcisi.

    Data API'den ayrı bir servis: `videos.list` yalnızca izlenme sayısı verir,
    retention vermez. Bu modülün ilgilendiği asıl metrik retention.
    """
    creds = publish.credentials(channel, required_scope=publish.ANALYTICS_SCOPE)

    from googleapiclient.discovery import build

    return build("youtubeAnalytics", "v2", credentials=creds, cache_discovery=False)


def _query_video(service, video_id: str, published_at: datetime) -> dict[str, Any]:
    """Tek videonun ömür boyu metrikleri."""
    response = (
        service.reports()
        .query(
            ids="channel==MINE",
            startDate=published_at.date().isoformat(),
            endDate=date.today().isoformat(),
            metrics="views,averageViewDuration,averageViewPercentage",
            filters=f"video=={video_id}",
        )
        .execute()
    )

    rows = response.get("rows") or []
    if not rows:
        # Video çok yeni veya henüz hiç izlenmemiş — hata değil, veri yok.
        return {"views": 0, "averageViewDuration": 0, "averageViewPercentage": 0.0}

    views, duration, percentage = rows[0][:3]
    return {
        "views": int(views or 0),
        "averageViewDuration": int(duration or 0),
        "averageViewPercentage": float(percentage or 0.0),
    }


def _parse_published(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _old_enough(published_at: datetime) -> bool:
    age = datetime.now(UTC) - published_at
    return age >= timedelta(days=config.ANALYTICS_MIN_VIDEO_AGE_DAYS)


class Fetcher:
    """Ölçüm kaynağı. Testlerde sahte bir kaynakla değiştirilebilir."""

    def __call__(self, channel: config.Channel, video_id: str, published_at: datetime) -> dict:
        return _query_video(_analytics_service(channel), video_id, published_at)


def refresh(
    channel: config.Channel = config.Channel.BEDTIME,
    fetcher: Fetcher | None = None,
) -> list[VideoStats]:
    """Yayınlanmış bölümlerin ölçümlerini tazeler ve DB'ye yazar.

    Yeterince eskimemiş videolar atlanır — hata değil, henüz ölçülebilir
    değiller. Tek bir videonun hatası diğerlerini durdurmaz; kanalın geri
    beslemesi bir videonun API hatası yüzünden tamamen durmamalı.
    """
    fetch = fetcher or Fetcher()
    out: list[VideoStats] = []

    for job in db.published_awaiting_analytics(channel.value):
        published_at = _parse_published(job["published_at"])
        if published_at is None or not _old_enough(published_at):
            continue

        try:
            raw = fetch(channel, job["youtube_video_id"], published_at)
        except Exception as exc:  # noqa: BLE001 — tek video hattı durduramaz
            print(f"  atlandı (iş #{job['id']}): {exc}")
            continue

        stats = VideoStats(
            job_id=job["id"],
            youtube_video_id=job["youtube_video_id"],
            views=int(raw.get("views", 0)),
            avg_view_duration_s=int(raw.get("averageViewDuration", 0)),
            retention_pct=float(raw.get("averageViewPercentage", 0.0)),
        )
        db.record_analytics(
            job_id=stats.job_id,
            youtube_video_id=stats.youtube_video_id,
            views=stats.views,
            avg_view_duration_s=stats.avg_view_duration_s,
            retention_pct=stats.retention_pct,
        )
        out.append(stats)

    return out


# --------------------------------------------------------------------------
# Eksen performansı
# --------------------------------------------------------------------------

@dataclass
class AxisScore:
    axis: str
    value: str
    samples: int
    mean_retention: float
    weight: float

    @property
    def confident(self) -> bool:
        return self.samples >= config.ANALYTICS_MIN_SAMPLES


def _premise_of(job: dict[str, Any]) -> dict[str, Any]:
    try:
        return json.loads(job.get("storyboard_json") or "{}").get("premise", {}) or {}
    except (json.JSONDecodeError, AttributeError):
        return {}


def axis_performance(channel: config.Channel) -> dict[str, list[AxisScore]]:
    """Her eksen değerinin ortalama retention'ı ve ondan türeyen ağırlığı.

    Ağırlık, değerin kanal ortalamasından sapmasıyla orantılı ve kırpılmış:

        weight = 1 + BOOST × (değer_ort − kanal_ort) / kanal_ort

    Kanal ortalaması payda olduğu için ölçek bağımsız — %20 retention'lı bir
    kanalda da %60'lık bir kanalda da aynı davranır.
    """
    rows = db.published_with_analytics(channel.value)
    scored: dict[str, list[AxisScore]] = {axis: [] for axis in WEIGHTED_AXES}
    if not rows:
        return scored

    overall = sum(float(r["retention_pct"] or 0.0) for r in rows) / len(rows)
    if overall <= 0:
        return scored

    buckets: dict[str, dict[str, list[float]]] = {
        axis: defaultdict(list) for axis in WEIGHTED_AXES
    }
    for row in rows:
        premise = _premise_of(row)
        for axis in WEIGHTED_AXES:
            value = premise.get(axis)
            if value:
                buckets[axis][str(value)].append(float(row["retention_pct"] or 0.0))

    for axis, values in buckets.items():
        for value, retentions in values.items():
            mean = sum(retentions) / len(retentions)
            if len(retentions) < config.ANALYTICS_MIN_SAMPLES:
                # Veri yetersiz — nötr. Tek şanslı video havuzu domine edemez.
                weight = 1.0
            else:
                raw = 1.0 + config.ANALYTICS_BOOST * (mean - overall) / overall
                weight = max(
                    config.ANALYTICS_MIN_WEIGHT, min(config.ANALYTICS_MAX_WEIGHT, raw)
                )
            scored[axis].append(
                AxisScore(
                    axis=axis,
                    value=value,
                    samples=len(retentions),
                    mean_retention=mean,
                    weight=weight,
                )
            )

    for axis in scored:
        scored[axis].sort(key=lambda s: s.mean_retention, reverse=True)

    return scored


def axis_weights(channel: config.Channel) -> dict[str, dict[str, float]]:
    """ideation'ın tükettiği biçim: {eksen: {değer: ağırlık}}.

    Havuzda olup burada olmayan değerler nötr (1.0) sayılır — yeni eklenen bir
    mekân, ölçülmediği için cezalandırılmamalı.
    """
    return {
        axis: {s.value: s.weight for s in scores}
        for axis, scores in axis_performance(channel).items()
    }


def summary(channel: config.Channel = config.Channel.BEDTIME) -> dict[str, Any]:
    """CLI ve doctor için özet."""
    rows = db.published_with_analytics(channel.value)
    if not rows:
        return {"measured": 0, "mean_retention": 0.0, "total_views": 0, "axes": {}}

    return {
        "measured": len(rows),
        "mean_retention": sum(float(r["retention_pct"] or 0.0) for r in rows) / len(rows),
        "total_views": sum(int(r["views"] or 0) for r in rows),
        "axes": axis_performance(channel),
    }


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Yayın sonrası performans")
    parser.add_argument("--channel", default="bedtime")
    parser.add_argument("--refresh", action="store_true", help="YouTube'dan ölçümleri çek")
    args = parser.parse_args()

    channel = config.Channel(args.channel)

    if args.refresh:
        stats = refresh(channel)
        print(f"{len(stats)} video ölçüldü.")
        for s in stats:
            print(f"  #{s.job_id}  {s.summary()}")
        return 0

    s = summary(channel)
    print(f"{s['measured']} ölçülmüş video, ortalama tutma %{s['mean_retention']:.1f}")
    for axis, scores in s["axes"].items():
        print(f"\n  {axis}:")
        for sc in scores[:5]:
            mark = "" if sc.confident else "  (veri yetersiz)"
            print(f"    {sc.value:<32} %{sc.mean_retention:5.1f}  ×{sc.weight:.2f}{mark}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
