"""Uyumluluk testleri — yapılandırmanın politika ihlaline izin vermediğini kanıtlar."""

from __future__ import annotations

import dataclasses

from core import config


def test_cocuk_kanallari_mfk_isaretli():
    """13 yaş altına yönelik her kanal Made for Kids olmalı."""
    for ch, profile in config.CHANNELS.items():
        upper = int(profile.age_range.split("-")[-1])
        if upper < 13:
            assert profile.made_for_kids, (
                f"{ch.value} hedef yaş {profile.age_range} ama MFK değil — "
                f"yanlış sınıflandırma"
            )


def test_yanlis_siniflandirma_dogrulamada_yakalanir(monkeypatch):
    """Biri RPM için MFK bayrağını kapatırsa validate() bunu yakalamalı."""
    bozuk = dataclasses.replace(
        config.CHANNELS[config.Channel.STORYTIME], made_for_kids=False
    )
    monkeypatch.setitem(config.CHANNELS, config.Channel.STORYTIME, bozuk)

    problems = config.validate()

    assert any("made_for_kids=False" in p for p in problems)
    assert any("COPPA" in p for p in problems)


def test_uzun_form_midroll_esigini_gecer():
    """8 dk altında mid-roll reklam açılmıyor — hiçbir uzun-form format altına inmemeli."""
    for ch, profile in config.CHANNELS.items():
        for name, fmt in profile.formats.items():
            if name == "short":
                continue
            assert fmt.min_seconds >= config.MIDROLL_THRESHOLD_SECONDS, (
                f"{ch.value}/{name} min {fmt.min_seconds}sn < "
                f"{config.MIDROLL_THRESHOLD_SECONDS}sn"
            )


def test_shorts_60_saniye_altinda():
    for ch, profile in config.CHANNELS.items():
        short = profile.formats.get("short")
        if short:
            assert short.max_seconds < 60, f"{ch.value} shorts 60sn'yi aşıyor"


def test_kadans_mutlak_tavani_asmaz():
    """Aktif kanal sayısı x haftalık kadans, mutlak günlük tavanı aşamaz."""
    aktif = len(config.active_channels())
    for name, cadence in config.CADENCE_PHASES.items():
        günlük = cadence.episodes_per_week_per_channel / 7 * aktif
        assert günlük <= config.HARD_DAILY_CAP_LONGFORM, (
            f"{name} fazı günlük {günlük:.1f} uzun-form üretir, "
            f"tavan {config.HARD_DAILY_CAP_LONGFORM}"
        )
        assert cadence.shorts_per_day <= config.HARD_DAILY_CAP_SHORTS


def test_baslangicta_tek_kanal_aktif():
    """Öğrenme fazı: tek kanal. İkincisi 30+ video ve retention verisinden sonra."""
    aktif = config.active_channels()
    assert list(aktif) == [config.Channel.BEDTIME], (
        f"Beklenen tek aktif kanal bedtime, bulunan: {[c.value for c in aktif]}"
    )


def test_pasif_kanal_tanimli_kalir():
    """Kanal B silinmedi, sadece pasif — açılmaya hazır."""
    assert config.Channel.STORYTIME in config.CHANNELS
    assert not config.CHANNELS[config.Channel.STORYTIME].active


def test_varsayilan_yapilandirma_saglam():
    assert config.validate() == []


def test_onay_kapisi_varsayilan_acik():
    assert config.REQUIRE_HUMAN_APPROVAL, (
        "Onay kapısı varsayılan olarak açık olmalı — inauthentic content riski"
    )
