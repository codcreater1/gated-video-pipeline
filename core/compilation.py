"""DERLEME — yayınlanmış bölümlerden 40-60 dakikalık tek video.

Bu format render EDİLMEZ, BİRLEŞTİRİLİR. Gerekçe ölçülmüş: 60 dakikalık tek
parça render bu makinede ~2.3 saat sürüyor (docs/benchmarks.md), oysa hazır
bölümleri `ffmpeg concat` ile stream-copy olarak birleştirmek saniyeler.
Bölümler aynı codec/çözünürlük/fps ile üretildiği için yeniden kodlama gerekmez.

`core/render.py::concat` bu işi zaten yapıyordu ama hiçbir yerden çağrılmıyordu;
bu modül onu hatta bağlar.

**Varyasyon burada başka bir şey demek.** Derlemenin senaryosu, içindeki
bölümlerin senaryolarının toplamı — benzerlik ölçmek tanım gereği tavan verir.
Ölçülmesi gereken tek şey iki derlemenin aynı bölümleri paylaşıp paylaşmadığı:
aynı 12 bölümü farklı sırayla ikinci kez yayınlamak, tekrar sinyalinin en
çıplak hâli.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core import config, db, render, storyboard


class CompilationError(Exception):
    """Derleme üretilemedi."""


@dataclass
class CompilationPlan:
    channel: str
    members: list[dict[str, Any]] = field(default_factory=list)

    @property
    def member_ids(self) -> list[int]:
        return [int(m["id"]) for m in self.members]

    @property
    def total_seconds(self) -> int:
        return sum(int(m["duration_seconds"] or 0) for m in self.members)

    def title(self) -> str:
        minutes = self.total_seconds // 60
        return f"{minutes} Minutes of Calm Bedtime Stories with Fen"


def _existing_member_sets(channel: str) -> list[set[int]]:
    """Önceki derlemelerin bölüm kümeleri."""
    out: list[set[int]] = []
    for job in db.recent_jobs(channel, limit=config.VARIATION_LOOKBACK, fmt="compilation"):
        try:
            board = json.loads(job["storyboard_json"] or "{}")
        except json.JSONDecodeError:
            continue
        members = board.get("compilation", {}).get("members") or []
        if members:
            out.append({int(m) for m in members})
    return out


def _jaccard(a: set[int], b: set[int]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


def member_overlap(member_ids: list[int], channel: str) -> float:
    """Bu bölüm kümesinin geçmiş derlemelerle en yüksek örtüşmesi."""
    current = set(member_ids)
    return max((_jaccard(current, prior) for prior in _existing_member_sets(channel)), default=0.0)


def select(
    channel: config.Channel,
    target_seconds: int | None = None,
) -> CompilationPlan:
    """Yayın sırasına göre bölüm toplar, hedef süreye ulaşınca durur.

    Sıra kasıtlı olarak yayın sırası: izleyici bölümleri anlatıldıkları
    sırayla görmeli. Rastgele sıralamak bölümler arası tonu bozuyor —
    palet bölüm sonuna doğru koyulaşıyor ve rastgele sıra bunu tersine çeviriyor.
    """
    fmt = config.CHANNELS[channel].formats.get("compilation")
    if fmt is None:
        raise CompilationError(f"{channel.value} kanalında derleme formatı tanımlı değil.")

    target = target_seconds or fmt.target_seconds
    episodes = db.published_by_format(channel.value, "episode")

    plan = CompilationPlan(channel=channel.value)
    for episode in episodes:
        if plan.total_seconds >= target:
            break
        if not (episode["output_path"] and Path(episode["output_path"]).exists()):
            # Dosyası silinmiş bölüm — sessizce atlanır, derleme durmaz.
            continue
        plan.members.append(episode)

    if plan.total_seconds < fmt.min_seconds:
        raise CompilationError(
            f"Yeterli yayınlanmış bölüm yok: {plan.total_seconds}sn toplandı, "
            f"en az {fmt.min_seconds}sn gerekli "
            f"({len(plan.members)} bölüm bulundu)."
        )
    return plan


def build(
    channel: config.Channel = config.Channel.BEDTIME,
    target_seconds: int | None = None,
    concat=None,
) -> tuple[int, CompilationPlan]:
    """Derlemeyi kurar ve birleştirir. Onay kuyruğuna bırakmaz."""
    plan = select(channel, target_seconds=target_seconds)

    overlap = member_overlap(plan.member_ids, channel.value)
    if overlap > config.COMPILATION_MAX_MEMBER_OVERLAP:
        raise CompilationError(
            f"Bu derleme geçmiş bir derlemeyle %{overlap * 100:.0f} örtüşüyor "
            f"(sınır %{config.COMPILATION_MAX_MEMBER_OVERLAP * 100:.0f}). "
            f"Aynı bölümleri yeniden yayınlamak doğrudan tekrar sinyali. "
            f"Yeni bölümler yayınlanmasını bekle."
        )

    job_id = db.create_job(channel.value, "compilation", topic=plan.title())

    # Sahne listesi üye bölümlerden kurulur: hem denetlenebilir kalıyor hem
    # `variation_guard.structure_hash` anlamlı bir iskelet görüyor (üye sayısı
    # ve süre profili), boş bir listede olduğu gibi hep aynı hash'e düşmüyor.
    board = {
        "premise": {"channel": channel.value, "protagonist": "Fen"},
        "title": plan.title(),
        "description": "A long, calm compilation of bedtime stories with Fen.",
        "scenes": [
            {
                "index": i,
                "narration": "",
                "setting": "",
                "action": "",
                "mood": "calm",
                "duration_seconds": int(m["duration_seconds"] or 0),
                "transition": "cut",
                "assets": {},
            }
            for i, m in enumerate(plan.members)
        ],
        "compilation": {
            "members": plan.member_ids,
            "titles": [m["title"] for m in plan.members],
        },
    }

    db.update_job(
        job_id,
        status=db.JobStatus.RENDERING.value,
        title=plan.title(),
        storyboard_json=storyboard.to_json(board),
        duration_seconds=plan.total_seconds,
    )

    output = config.OUTPUT_DIR / f"compilation_{job_id}.mp4"
    joiner = concat or render.concat
    try:
        result = joiner([Path(m["output_path"]) for m in plan.members], output)
    except Exception as exc:
        db.update_job(
            job_id, status=db.JobStatus.FAILED.value, rejection_reason=str(exc)
        )
        raise CompilationError(f"Birleştirme başarısız: {exc}") from exc

    path = getattr(result, "output_path", output)
    db.update_job(job_id, output_path=str(path))
    return job_id, plan
