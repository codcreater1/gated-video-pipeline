"""Orkestratör — hattı uçtan uca yürütür ve kapıları sırayla uygular.

n8n bu modülü çağırır; iş mantığı burada, zamanlama ve bildirim orada.

Aşama sırası kasıtlıdır:

    kadans → bütçe → senaryo → seslendirme → VARYASYON ⛔ → render → ONAY ⛔ → yayın

İki sıralama kararı önemli:

- **Varyasyon kapısı render'dan ÖNCE.** Reddedilecek bir videoyu render etmek bu
  makinede ~23 dakika harcamak demek olurdu.
- **Seslendirme varyasyondan ÖNCE.** Kapının ses ekseni hangi sesin kullanıldığını
  bilmek zorunda ve ses seçimi seslendirme aşamasında yapılıyor. Ayrıca sahne
  süreleri ancak gerçek ses üretilince kesinleşiyor — senaryodaki süreler tahmin.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from core import (
    approval,
    budget,
    config,
    db,
    ideation,
    narration,
    render,
    script,
    storyboard,
    variation_guard,
)


class ScriptGenerator(Protocol):
    """Senaryo üreteci. Testlerde sahte bir üreteçle değiştirilebilir."""

    def __call__(
        self, job_id: int, premise: ideation.Premise, fmt: str
    ) -> script.ScriptResult: ...


@dataclass
class StageResult:
    job_id: int
    stage: str
    ok: bool
    detail: str
    payload: dict[str, Any] | None = None

    def __bool__(self) -> bool:
        return self.ok


class CadenceExceeded(Exception):
    """Günlük tavan doldu."""


# --------------------------------------------------------------------------
# Kadans kapısı
# --------------------------------------------------------------------------

def check_cadence(channel: config.Channel, fmt: str) -> StageResult:
    """Bugünkü yayın sayısı mutlak tavanı aştı mı?

    Bu, inauthentic content riskini yöneten ilk savunma hattı. Kadans fazı
    haftalık hedefi belirler; mutlak tavan hiçbir fazın aşamayacağı sert sınır.
    """
    cap = (
        config.HARD_DAILY_CAP_SHORTS if fmt == "short" else config.HARD_DAILY_CAP_LONGFORM
    )
    published = db.published_today()

    if published >= cap:
        return StageResult(
            0, "kadans", False,
            f"Bugün {published} video yayınlandı, mutlak tavan {cap}. Üretim durdu.",
        )
    return StageResult(0, "kadans", True, f"Bugün {published}/{cap} yayınlandı.")


# --------------------------------------------------------------------------
# Aşamalar
# --------------------------------------------------------------------------

def create_job(channel: config.Channel, fmt: str = "episode") -> tuple[int, ideation.Premise]:
    """Fikir üretir, bileşimi rezerve eder ve işi kuyruğa alır."""
    premise = ideation.generate(channel)
    job_id = db.create_job(channel.value, fmt, topic=premise.summary())
    ideation.reserve(premise)
    return job_id, premise


def write_script(
    job_id: int,
    premise: ideation.Premise,
    fmt: str,
    generator: ScriptGenerator | None = None,
) -> StageResult:
    db.update_job(job_id, status=db.JobStatus.SCRIPTING.value)
    gen = generator or script.generate

    try:
        result = gen(job_id, premise, fmt)
    except budget.BudgetExceeded as exc:
        db.update_job(job_id, status=db.JobStatus.FAILED.value, rejection_reason=str(exc))
        return StageResult(job_id, "senaryo", False, f"BÜTÇE: {exc}")
    except Exception as exc:
        db.update_job(job_id, status=db.JobStatus.FAILED.value, rejection_reason=str(exc))
        return StageResult(job_id, "senaryo", False, f"Senaryo üretilemedi: {exc}")

    board = storyboard.build(premise, result.episode)
    db.update_job(
        job_id,
        status=db.JobStatus.STORYBOARDING.value,
        title=result.episode.title,
        script=result.episode.full_script,
        storyboard_json=storyboard.to_json(board),
        duration_seconds=int(result.estimated_duration),
    )

    return StageResult(
        job_id, "senaryo", True,
        f"{len(result.episode.scenes)} sahne, ~{int(result.estimated_duration)}sn, "
        f"${result.cost_usd:.2f}, {result.rewrites} düzeltme",
        payload={"storyboard": board, "result": result},
    )


class Narrator(Protocol):
    """Seslendirici. Testlerde sahte bir üreteçle değiştirilebilir."""

    def __call__(
        self, job_id: int, storyboard: dict[str, Any], channel: config.Channel
    ) -> narration.NarrationResult: ...


def narrate(
    job_id: int, channel: config.Channel, narrator: Narrator | None = None
) -> StageResult:
    """Seslendirme — sahne sürelerini GERÇEK ses uzunluğuyla günceller.

    Varyasyon kapısından ÖNCE çalışır çünkü kapının ses ekseni hangi sesin
    kullanıldığını bilmek zorunda; ses seçimi burada yapılıyor.
    """
    job = db.get_job(job_id)
    if job is None:
        raise ValueError(f"İş bulunamadı: {job_id}")

    board = json.loads(job["storyboard_json"] or "{}")
    synth = narrator or narration.narrate

    try:
        result = synth(job_id, board, channel)
    except Exception as exc:
        db.update_job(job_id, status=db.JobStatus.FAILED.value, rejection_reason=str(exc))
        return StageResult(job_id, "seslendirme", False, f"Seslendirilemedi: {exc}")

    db.update_job(
        job_id,
        storyboard_json=storyboard.to_json(result.storyboard),
        duration_seconds=int(result.total_seconds),
        voice_id=result.voice_id,
    )

    return StageResult(
        job_id, "seslendirme", True,
        f"{result.scene_count} sahne, {int(result.total_seconds)}sn, ses: {result.voice_id}",
        payload={"narration": result},
    )


def check_variation(job_id: int, voice_id: str) -> StageResult:
    """⛔ VARYASYON KAPISI — render'dan önce."""
    job = db.get_job(job_id)
    if job is None:
        raise ValueError(f"İş bulunamadı: {job_id}")

    board = json.loads(job["storyboard_json"] or "{}")
    verdict = variation_guard.enforce(
        job_id=job_id,
        channel=job["channel"],
        script=job["script"] or "",
        storyboard=board,
        title=job["title"] or "",
        # Kahraman hariç — tekrar etmesi beklenen varlık kapıyı kilitlerdi.
        asset_ids=storyboard.variation_asset_ids(board),
        voice_id=voice_id,
    )

    notes = [f"{c.axis}: {c.detail}" for c in verdict.checks]
    return StageResult(
        job_id, "varyasyon", verdict.passed, verdict.reason, payload={"notes": notes}
    )


def _default_renderer(job_id: int) -> Path:
    """Gerçek render — Remotion. Testler bunun yerine sahte bir üreteç geçirir."""
    job = db.get_job(job_id)
    if job is None:
        raise ValueError(f"İş bulunamadı: {job_id}")

    board = json.loads(job["storyboard_json"] or "{}")
    result = render.render_episode(
        job_id=job_id,
        storyboard=board,
        audio_dir=narration.audio_dir_for(job_id),
    )
    return result.output_path


def submit_for_approval(job_id: int, variation_notes: list[str]) -> StageResult:
    """⛔ ONAY KAPISI — inceleme kartını kuyruğa koyar."""
    card = approval.submit(job_id, variation_notes=variation_notes)
    return StageResult(
        job_id, "onay", True,
        f"İnceleme kuyruğunda: {card.title}",
        payload={"card": card.to_dict()},
    )


# --------------------------------------------------------------------------
# Uçtan uca
# --------------------------------------------------------------------------

def run(
    channel: config.Channel = config.Channel.BEDTIME,
    fmt: str = "episode",
    generator: ScriptGenerator | None = None,
    narrator: Narrator | None = None,
    renderer=None,
) -> list[StageResult]:
    """Bir videoyu üretim hattından geçirir.

    Herhangi bir kapı düşerse orada durur ve o ana kadarki sonuçları döner.
    Yayın YAPMAZ — onay kuyruğunda bırakır.
    """
    results: list[StageResult] = []

    cadence = check_cadence(channel, fmt)
    results.append(cadence)
    if not cadence:
        return results

    profile = config.CHANNELS[channel]
    if not profile.active:
        results.append(StageResult(0, "kanal", False, f"{channel.value} pasif."))
        return results

    job_id, premise = create_job(channel, fmt)

    script_stage = write_script(job_id, premise, fmt, generator=generator)
    results.append(script_stage)
    if not script_stage:
        return results

    narration_stage = narrate(job_id, channel, narrator=narrator)
    results.append(narration_stage)
    if not narration_stage:
        return results

    chosen_voice = db.get_job(job_id)["voice_id"] or profile.voice_id
    variation = check_variation(job_id, chosen_voice)
    results.append(variation)
    if not variation:
        return results

    db.update_job(job_id, status=db.JobStatus.RENDERING.value)
    try:
        output_path = (renderer or _default_renderer)(job_id)
    except Exception as exc:
        db.update_job(job_id, status=db.JobStatus.FAILED.value, rejection_reason=str(exc))
        results.append(StageResult(job_id, "render", False, f"Render başarısız: {exc}"))
        return results

    db.update_job(job_id, output_path=str(output_path))
    results.append(StageResult(job_id, "render", True, str(output_path)))

    approval_stage = submit_for_approval(job_id, variation.payload["notes"])
    results.append(approval_stage)
    return results


def summary(results: list[StageResult]) -> str:
    lines = []
    for r in results:
        mark = "OK  " if r.ok else "DUR "
        lines.append(f"  [{mark}] {r.stage.ljust(10)} {r.detail}")
    return "\n".join(lines)
