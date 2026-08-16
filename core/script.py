"""Senaryo üretimi — Claude API.

Tasarım notları:

- **Yapılandırılmış çıktı** (`messages.parse` + Pydantic) kullanılır. Prefill
  Claude Opus 5'te 400 döner ve zaten kırılgan bir yöntemdi.
- **Sistem promptu dondurulmuştur** ve önbelleğe alınır. Kanal stil kılavuzu her
  çağrıda aynı bayt dizisi olduğu için prefix cache tutar; premise kullanıcı
  turunda gider. Sisteme tarih/ID gibi değişken hiçbir şey enjekte edilmez.
- **Süre hedefi** `voice.estimate_duration` ile doğrulanır. 10 dakikalık hedefe
  3 dakikalık metin yazmak boşa render demektir.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

import anthropic
from pydantic import BaseModel, Field

from core import budget, config, ideation, voice

# Sahne sayısı aralığı — varyasyon kapısının "yapı" ekseni bunu kullanır.
MIN_SCENES = 5
MAX_SCENES = 12

# Süre toleransı: hedefin ±%15'i kabul edilir.
DURATION_TOLERANCE = 0.15
MAX_REWRITES = 2

# Claude Opus 5 fiyatı: $5 / MTok girdi, $25 / MTok çıktı.
USD_PER_INPUT_TOKEN = 5.0 / 1_000_000
USD_PER_OUTPUT_TOKEN = 25.0 / 1_000_000


class Scene(BaseModel):
    """Tek bir sahne. Storyboard ve render bunu tüketir."""

    narration: str = Field(description="Bu sahnede seslendirilecek metin.")
    setting: str = Field(description="Sahnenin geçtiği yer, kısa betimleme.")
    action: str = Field(description="Karakterin bu sahnede yaptığı şey.")
    mood: str = Field(description="Sahnenin duygusu: calm, curious, warm, gentle, resolved.")
    duration_seconds: int = Field(description="Bu sahnenin tahmini süresi.")
    transition: str = Field(description="Sonraki sahneye geçiş: fade, cut, dissolve, wipe.")


class Episode(BaseModel):
    title: str = Field(description="YouTube başlığı, İngilizce, 60 karakterden kısa.")
    description: str = Field(description="YouTube açıklaması, 2-3 cümle, İngilizce.")
    scenes: list[Scene]

    @property
    def full_script(self) -> str:
        return "\n\n".join(s.narration for s in self.scenes)

    @property
    def total_duration(self) -> int:
        return sum(s.duration_seconds for s in self.scenes)


@dataclass
class ScriptResult:
    episode: Episode
    cost_usd: float
    rewrites: int
    estimated_duration: float


# --------------------------------------------------------------------------
# Sistem promptu — DONDURULMUŞ. Değişken hiçbir şey enjekte edilmez.
# --------------------------------------------------------------------------

_BEDTIME_SYSTEM = """\
You write bedtime stories for a YouTube channel aimed at children aged 2-5.

# The character

Every episode follows Fen, a young otter who lives in a mossy streambed. Fen is \
calm, helpful, and never in a hurry. Fen notices things other animals miss, and \
helps without being asked — but Fen is a small animal in a large world, not a hero \
who fixes everything. Sometimes Fen simply keeps someone company.

Fen is the constant. Each episode brings one guest — another animal Fen meets, \
helps, or learns from. The guest changes every time; Fen does not.

Refer to Fen by name, never "the otter". Do not describe Fen's appearance — the \
animation handles that, and written descriptions drift from the visuals over time.

# What makes an episode work

Each episode is its own complete story with a beginning, a middle, and an ending. \
A child should be able to say what happened afterward. The character wants something, \
tries, and gets somewhere — that is the whole job. An episode where a character only \
moves between pretty settings is a failure.

The pace is slow and the tone is warm. Tension resolves quickly and gently. There is \
no peril, no villain, no loud surprise. The ending settles rather than concludes: the \
character comes to rest, and the last scene is quiet.

Curiosity carries the story, not sleep. Do not write "and then she fell asleep" as the \
point of the episode. Sleep is where the viewer ends up, not what the story is about.

# Voice

Short sentences. Concrete nouns. Present-tense action described plainly. Write for a \
narrator reading aloud slowly — the text is heard, never read. Avoid wordplay, irony, \
and any joke that depends on knowing something.

# Hard constraints

Never include: illness or medical content, money or finance, law, politics, religion, \
violence, danger, death, separation distress, food or body-size themes, brands or \
products, real people.

# Scene structure

Between 5 and 12 scenes. Each scene carries one beat of the story and names a setting \
and an action. Vary scene lengths — an episode where every scene is the same length \
reads as a template, and templated episodes cannot be monetized on YouTube.

Write the narration text only. No stage directions, no "Scene 1:", no sound cues.\
"""


def _system_prompt(channel: config.Channel) -> str:
    # Şimdilik tek aktif kanal. Kanal B açıldığında kendi dondurulmuş promptu eklenir.
    return _BEDTIME_SYSTEM


def _user_turn(premise: ideation.Premise, target_seconds: int, target_words: int) -> str:
    beats = "\n".join(f"{i}. {b}" for i, b in enumerate(premise.shape["beats"], 1))
    return f"""\
Write one episode.

Guest this episode: {premise.character}
Setting: {premise.setting}
What the story is about: {premise.topic}

Narrative shape — follow these beats in order:
{beats}

Target length: about {target_words} words of narration, which reads aloud in roughly \
{target_seconds // 60} minutes at this channel's slow pace. Scene durations should sum \
to about {target_seconds} seconds.

Translate the guest and setting into natural English — they are given in Turkish \
as production notes, not as words to use in the story. Give the guest a short, \
sayable name a toddler could repeat."""


# --------------------------------------------------------------------------
# Üretim
# --------------------------------------------------------------------------

def _client() -> anthropic.Anthropic:
    if not os.getenv("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY tanımlı değil. .env dosyasına ekle."
        )
    return anthropic.Anthropic()


def _call_cost(usage) -> float:
    """Girdi + çıktı token maliyeti. Önbellek okumaları ~0.1x fiyatlanır."""
    cached = getattr(usage, "cache_read_input_tokens", 0) or 0
    written = getattr(usage, "cache_creation_input_tokens", 0) or 0
    fresh = usage.input_tokens
    return (
        fresh * USD_PER_INPUT_TOKEN
        + cached * USD_PER_INPUT_TOKEN * 0.1
        + written * USD_PER_INPUT_TOKEN * 1.25
        + usage.output_tokens * USD_PER_OUTPUT_TOKEN
    )


def _words_for(target_seconds: int, speech_rate: float) -> int:
    """Hedef süreyi kelime sayısına çevirir (Kokoro ~165 kelime/dk temel hız)."""
    return int(target_seconds / 60 * 165 * speech_rate)


def generate(
    job_id: int,
    premise: ideation.Premise,
    fmt: str = "episode",
) -> ScriptResult:
    """Senaryo üretir ve süre hedefine oturana kadar en fazla MAX_REWRITES kez düzeltir.

    Bütçe kapısından geçer — her API çağrısı öncesi izin alınır.
    """
    channel = config.Channel(premise.channel)
    profile = config.CHANNELS[channel]
    video_format = profile.formats[fmt]
    target = video_format.target_seconds
    target_words = _words_for(target, profile.speech_rate)

    client = _client()
    system = [
        {
            "type": "text",
            "text": _system_prompt(channel),
            "cache_control": {"type": "ephemeral"},
        }
    ]

    messages = [{"role": "user", "content": _user_turn(premise, target, target_words)}]
    total_cost = 0.0

    for attempt in range(MAX_REWRITES + 1):
        # Kapı: her çağrı öncesi. Tahmini maliyet ~$0.30 (güvenli üst sınır).
        decision = budget.check(job_id, 0.30)
        if not decision.allowed:
            raise budget.BudgetExceeded(decision.reason)

        response = client.messages.parse(
            model=config.SCRIPT_MODEL,
            max_tokens=16000,
            system=system,
            messages=messages,
            output_format=Episode,
        )

        cost = _call_cost(response.usage)
        total_cost += cost
        budget.commit(job_id, "llm", cost, f"senaryo deneme {attempt + 1}")

        if response.stop_reason == "refusal":
            raise RuntimeError(
                f"Senaryo üretimi reddedildi: "
                f"{getattr(response.stop_details, 'category', 'bilinmiyor')}. "
                f"Premise'i gözden geçir: {premise.summary()}"
            )

        episode = response.parsed_output
        problems = _validate(episode, video_format, profile.speech_rate)

        if not problems:
            return ScriptResult(
                episode=episode,
                cost_usd=total_cost,
                rewrites=attempt,
                estimated_duration=voice.estimate_duration(
                    episode.full_script, profile.speech_rate
                ),
            )

        if attempt == MAX_REWRITES:
            # Son deneme de tutmadı — eldekiyle devam et, QC kapısı son sözü söyler.
            return ScriptResult(
                episode=episode,
                cost_usd=total_cost,
                rewrites=attempt,
                estimated_duration=voice.estimate_duration(
                    episode.full_script, profile.speech_rate
                ),
            )

        messages = [
            *messages,
            {"role": "assistant", "content": episode.model_dump_json()},
            {
                "role": "user",
                "content": "Revise the episode. Problems to fix:\n"
                + "\n".join(f"- {p}" for p in problems)
                + "\n\nKeep what works; change only what the problems call for.",
            },
        ]

    raise AssertionError("ulaşılamaz")


def _validate(episode: Episode, fmt: config.VideoFormat, speech_rate: float) -> list[str]:
    """Süre ve yapı denetimi. Boş liste = sağlam."""
    problems: list[str] = []

    n = len(episode.scenes)
    if n < MIN_SCENES:
        problems.append(f"Only {n} scenes; need at least {MIN_SCENES}.")
    elif n > MAX_SCENES:
        problems.append(f"{n} scenes is too many; keep it under {MAX_SCENES}.")

    estimated = voice.estimate_duration(episode.full_script, speech_rate)
    low = fmt.target_seconds * (1 - DURATION_TOLERANCE)
    high = fmt.target_seconds * (1 + DURATION_TOLERANCE)

    if estimated < low:
        short_by = int(low - estimated)
        problems.append(
            f"Narration is about {int(estimated)}s when read aloud, "
            f"{short_by}s short of the {fmt.target_seconds}s target. Add more story."
        )
    elif estimated > high:
        over_by = int(estimated - high)
        problems.append(
            f"Narration runs about {int(estimated)}s, {over_by}s over target. Tighten it."
        )

    if len(episode.title) > 60:
        problems.append(f"Title is {len(episode.title)} characters; keep it under 60.")

    # Sahne süreleri birbirinin aynısıysa şablon kokusu verir — varyasyon kapısı
    # bunu zaten yakalar ama burada düzeltmek bir render turu kurtarır.
    durations = [s.duration_seconds for s in episode.scenes]
    if len(set(durations)) == 1 and len(durations) > 2:
        problems.append("Every scene is the same length; vary the pacing.")

    return problems
