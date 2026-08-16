"""Senaryo modülü testleri — API çağrısı yapmadan saf mantığı doğrular."""

from __future__ import annotations

import random

import pytest

from core import config, ideation, script


def _scene(narration: str, duration: int = 60, transition: str = "fade") -> script.Scene:
    return script.Scene(
        narration=narration,
        setting="quiet forest",
        action="walks slowly",
        mood="calm",
        duration_seconds=duration,
        transition=transition,
    )


def _episode(scene_count: int = 8, words_per_scene: int = 100, **kw) -> script.Episode:
    text = " ".join(["word"] * words_per_scene) + "."
    return script.Episode(
        title=kw.get("title", "Luna and the Sleepy Moon"),
        description="A gentle bedtime story.",
        scenes=[
            _scene(text, duration=50 + i * 10) for i in range(scene_count)
        ],
    )


BEDTIME = config.CHANNELS[config.Channel.BEDTIME]
EPISODE_FMT = BEDTIME.formats["episode"]


def test_hedef_kelime_sayisi_sureden_turetilir():
    """600 saniye @ 0.82 hız ≈ 1353 kelime."""
    words = script._words_for(600, 0.82)
    assert 1300 < words < 1400


def test_yavas_tempo_daha_az_kelime_ister():
    assert script._words_for(600, 0.82) < script._words_for(600, 1.0)


def test_sure_hedefindeki_bolum_gecer():
    hedef_kelime = script._words_for(EPISODE_FMT.target_seconds, BEDTIME.speech_rate)
    ep = _episode(scene_count=8, words_per_scene=hedef_kelime // 8)

    problems = script._validate(ep, EPISODE_FMT, BEDTIME.speech_rate)

    assert problems == [], problems


def test_cok_kisa_bolum_reddedilir():
    ep = _episode(scene_count=6, words_per_scene=20)

    problems = script._validate(ep, EPISODE_FMT, BEDTIME.speech_rate)

    assert any("short of the" in p for p in problems)


def test_cok_uzun_bolum_reddedilir():
    ep = _episode(scene_count=8, words_per_scene=600)

    problems = script._validate(ep, EPISODE_FMT, BEDTIME.speech_rate)

    assert any("over target" in p for p in problems)


def test_az_sahne_reddedilir():
    ep = _episode(scene_count=3, words_per_scene=400)

    problems = script._validate(ep, EPISODE_FMT, BEDTIME.speech_rate)

    assert any("at least" in p for p in problems)


def test_cok_sahne_reddedilir():
    ep = _episode(scene_count=15, words_per_scene=90)

    problems = script._validate(ep, EPISODE_FMT, BEDTIME.speech_rate)

    assert any("too many" in p for p in problems)


def test_uzun_baslik_reddedilir():
    hedef = script._words_for(EPISODE_FMT.target_seconds, BEDTIME.speech_rate)
    ep = _episode(
        scene_count=8,
        words_per_scene=hedef // 8,
        title="A Very Long Title That Goes On And On And Will Not Fit In The Player" * 2,
    )

    problems = script._validate(ep, EPISODE_FMT, BEDTIME.speech_rate)

    assert any("under 60" in p for p in problems)


def test_esit_sahne_sureleri_sablon_olarak_yakalanir():
    """Her sahne aynı uzunluktaysa şablon kokar — inauthentic content riski."""
    hedef = script._words_for(EPISODE_FMT.target_seconds, BEDTIME.speech_rate)
    text = " ".join(["word"] * (hedef // 8)) + "."
    ep = script.Episode(
        title="Luna and the Moon",
        description="A story.",
        scenes=[_scene(text, duration=75) for _ in range(8)],
    )

    problems = script._validate(ep, EPISODE_FMT, BEDTIME.speech_rate)

    assert any("same length" in p for p in problems)


def test_bolum_yardimcilari():
    ep = _episode(scene_count=4, words_per_scene=10)
    assert ep.full_script.count("word") == 40
    assert ep.total_duration == 50 + 60 + 70 + 80


def test_kullanici_turu_premise_alanlarini_tasir():
    premise = ideation.generate(config.Channel.BEDTIME, rng=random.Random(11))

    turn = script._user_turn(premise, 600, 1350)

    assert premise.character in turn
    assert premise.setting in turn
    assert premise.topic in turn
    for beat in premise.shape["beats"]:
        assert beat in turn


def test_sistem_promptu_degisken_icermez():
    """Prefix cache'in tutması için sistem promptu bayt bayt sabit olmalı."""
    a = script._system_prompt(config.Channel.BEDTIME)
    b = script._system_prompt(config.Channel.BEDTIME)
    assert a == b
    # Tarih, ID, sayaç gibi hiçbir dinamik iz olmamalı
    assert "{" not in a and "}" not in a


def test_sistem_promptu_yasakli_konulari_sayar():
    prompt = script._system_prompt(config.Channel.BEDTIME)
    for konu in ("medical", "money", "politics", "violence", "brands", "real people"):
        assert konu in prompt.lower()


def test_maliyet_hesabi_onbellegi_ucuzlatir():
    class Usage:
        input_tokens = 1000
        output_tokens = 2000
        cache_read_input_tokens = 0
        cache_creation_input_tokens = 0

    class Cached(Usage):
        input_tokens = 0
        cache_read_input_tokens = 1000

    tam = script._call_cost(Usage())
    onbellekli = script._call_cost(Cached())

    assert onbellekli < tam
    assert tam == pytest.approx(1000 * 5e-6 + 2000 * 25e-6)
