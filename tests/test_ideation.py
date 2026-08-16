"""Fikir üretimi testleri — tekrarın kaynağında önlendiğini kanıtlar."""

from __future__ import annotations

import json
import random

from core import config, db, ideation


def test_havuz_uzun_sure_yeter():
    """Cold start haftada 3 bölüm. Havuz yıllarca dayanmalı."""
    rapor = ideation.exhaustion_report(config.Channel.BEDTIME)
    assert rapor["total_combinations"] > 5000
    assert rapor["weeks_of_runway"] > 500


def test_uretilen_fikir_dolu():
    p = ideation.generate(config.Channel.BEDTIME, rng=random.Random(42))
    assert p.topic and p.setting and p.character
    assert p.shape["name"] and p.shape["beats"]
    assert len(p.combo_key) == 16


def test_ayni_bilesim_iki_kez_secilmez():
    rng = random.Random(7)
    ilk = ideation.generate(config.Channel.BEDTIME, rng=rng)
    ideation.reserve(ilk)

    # 30 üretim boyunca aynı bileşim bir daha çıkmamalı
    for _ in range(30):
        p = ideation.generate(config.Channel.BEDTIME, rng=rng)
        assert p.combo_key != ilk.combo_key


def test_reserve_sayaci_arttirir():
    p = ideation.generate(config.Channel.BEDTIME, rng=random.Random(1))
    ideation.reserve(p)
    ideation.reserve(p)

    with db.connect() as conn:
        row = conn.execute(
            "SELECT used_count FROM topics WHERE channel = ? AND topic = ?",
            (p.channel, p.combo_key),
        ).fetchone()
    assert row["used_count"] == 2


def _publish_with_premise(premise: ideation.Premise) -> int:
    job = db.create_job(premise.channel, "episode", topic=premise.topic)
    db.update_job(
        job,
        script="metin",
        title="baslik",
        storyboard_json=json.dumps({"premise": premise.to_dict(), "scenes": []}),
        status=db.JobStatus.PUBLISHED.value,
    )
    return job


def test_son_bolumlerin_sekli_tekrar_secilmez():
    """Yapı ekseninin kaynak önlemi: son 3 bölümün anlatı şekli bloklanır."""
    rng = random.Random(99)
    kullanilan = []
    for _ in range(3):
        p = ideation.generate(config.Channel.BEDTIME, rng=rng)
        _publish_with_premise(p)
        ideation.reserve(p)
        kullanilan.append(p.shape["name"])

    yeni = ideation.generate(config.Channel.BEDTIME, rng=rng)
    assert yeni.shape["name"] not in kullanilan


def test_son_bolumlerin_karakteri_tekrar_secilmez():
    rng = random.Random(5)
    karakterler = []
    for _ in range(4):
        p = ideation.generate(config.Channel.BEDTIME, rng=rng)
        _publish_with_premise(p)
        ideation.reserve(p)
        karakterler.append(p.character)

    yeni = ideation.generate(config.Channel.BEDTIME, rng=rng)
    assert yeni.character not in karakterler


def test_combo_key_deterministik():
    a = ideation.Premise("bedtime", "t", "s", "c", ideation.NARRATIVE_SHAPES[0])
    b = ideation.Premise("bedtime", "t", "s", "c", ideation.NARRATIVE_SHAPES[0])
    farkli = ideation.Premise("bedtime", "t", "s", "c", ideation.NARRATIVE_SHAPES[1])

    assert a.combo_key == b.combo_key
    assert a.combo_key != farkli.combo_key


def test_havuz_tukenirse_kilitlenmez():
    """Tüm bileşimler kullanılmış olsa bile üretim durmaz — kapı son sözü söyler."""
    rng = random.Random(3)
    for _ in range(60):
        ideation.reserve(ideation.generate(config.Channel.BEDTIME, rng=rng))

    p = ideation.generate(config.Channel.BEDTIME, max_attempts=10, rng=rng)
    assert p is not None


def test_konu_havuzu_uyku_klisesine_dusmemis():
    """Her bölüm 'X uyudu' varyantı olsaydı inauthentic content riski doğardı."""
    uyku_kelimeleri = {"uyku", "uyudu", "uyumak", "uykuya"}
    uyku_temali = [
        t for t in ideation.BEDTIME_TOPICS
        if any(k in t.lower() for k in uyku_kelimeleri)
    ]
    assert len(uyku_temali) == 0, f"Uyku klişesi konular: {uyku_temali}"
