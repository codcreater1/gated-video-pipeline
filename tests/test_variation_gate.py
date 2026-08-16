"""VARYASYON KAPISI testleri.

Kritik test: kasıtlı kopya senaryo REDDEDİLMELİ. Bu kapı çalışmıyorsa proje,
YouTube'un inauthentic content politikası karşısında Screen Culture ve KH Studio
ile aynı sona gider.
"""

from __future__ import annotations

from core import db
from core import variation_guard as vg

STORYBOARD_A = {
    "scenes": [
        {"duration_seconds": 60, "transition": "fade"},
        {"duration_seconds": 90, "transition": "cut"},
        {"duration_seconds": 75, "transition": "fade"},
    ]
}

STORYBOARD_B = {
    "scenes": [
        {"duration_seconds": 40, "transition": "dissolve"},
        {"duration_seconds": 55, "transition": "cut"},
        {"duration_seconds": 120, "transition": "wipe"},
        {"duration_seconds": 35, "transition": "fade"},
    ]
}

SCRIPT_MOON = (
    "Luna the little owl could not sleep. She flew softly above the quiet forest, "
    "past the sleeping rabbits and the still pond, looking for the moon. "
    "The moon smiled and sang her a gentle song until her eyes grew heavy."
)

SCRIPT_RIVER = (
    "Milo the badger packed a small basket and followed the winding river. "
    "He counted seven smooth stones, shared bread with a heron, and built a raft "
    "from fallen branches before the afternoon storm arrived."
)


def _publish(channel: str, script: str, storyboard, title, assets, voice) -> int:
    """Yayınlanmış bir video simüle eder — geçmişe girer."""
    job = db.create_job(channel, "episode")
    db.update_job(job, script=script, title=title, status=db.JobStatus.PUBLISHED.value)
    vg.commit_fingerprint(job, channel, storyboard, title, assets, voice)
    return job


# --------------------------------------------------------------------------
# Senaryo ekseni
# --------------------------------------------------------------------------

def test_bos_gecmiste_her_sey_gecer():
    verdict = vg.evaluate(
        "bedtime", SCRIPT_MOON, STORYBOARD_A, "Luna and the Moon", ["a", "b"], "af_bella"
    )
    assert verdict.passed, verdict.reason


def test_ayni_senaryo_reddedilir():
    """KRİTİK TEST: aynı senaryo ikinci kez geçemez."""
    _publish("bedtime", SCRIPT_MOON, STORYBOARD_A, "Luna and the Moon", ["a", "b"], "af_bella")

    verdict = vg.evaluate(
        "bedtime", SCRIPT_MOON, STORYBOARD_B, "Something Completely Different",
        ["x", "y"], "am_michael",
    )

    assert not verdict.passed
    assert any(c.axis == "senaryo" for c in verdict.failures)


def test_farkli_senaryo_gecer():
    _publish("bedtime", SCRIPT_MOON, STORYBOARD_A, "Luna and the Moon", ["a", "b"], "af_bella")

    verdict = vg.evaluate(
        "bedtime", SCRIPT_RIVER, STORYBOARD_B, "Milo Builds a Raft", ["x", "y"], "am_michael"
    )

    assert verdict.passed, verdict.reason


def test_kanallar_birbirini_etkilemez():
    """Kanal A'nın geçmişi Kanal B'yi engellemez."""
    _publish("bedtime", SCRIPT_MOON, STORYBOARD_A, "Luna and the Moon", ["a", "b"], "af_bella")

    verdict = vg.evaluate(
        "storytime", SCRIPT_MOON, STORYBOARD_A, "Luna and the Moon", ["a", "b"], "af_bella"
    )

    assert verdict.passed, verdict.reason


# --------------------------------------------------------------------------
# Yapı ekseni
# --------------------------------------------------------------------------

def test_ayni_yapi_iskeleti_reddedilir():
    _publish("bedtime", SCRIPT_MOON, STORYBOARD_A, "Luna and the Moon", ["a"], "af_bella")

    verdict = vg.evaluate(
        "bedtime", SCRIPT_RIVER, STORYBOARD_A, "Milo Builds a Raft", ["z"], "am_michael"
    )

    assert not verdict.passed
    assert any(c.axis == "yapı" for c in verdict.failures)


def test_yapi_hash_sure_profilini_yakalar():
    """Birkaç saniyelik fark aynı iskelet sayılır — 5sn kovalarına yuvarlanır."""
    yakin = {"scenes": [{"duration_seconds": 62, "transition": "fade"},
                        {"duration_seconds": 91, "transition": "cut"},
                        {"duration_seconds": 77, "transition": "fade"}]}
    assert vg.structure_hash(STORYBOARD_A) == vg.structure_hash(yakin)
    assert vg.structure_hash(STORYBOARD_A) != vg.structure_hash(STORYBOARD_B)


# --------------------------------------------------------------------------
# Başlık ekseni
# --------------------------------------------------------------------------

def test_baslik_sablonu_cikarimi():
    assert vg.title_pattern("Luna and the Sleepy Moon") == vg.title_pattern(
        "Milo and the Quiet River"
    )
    assert vg.title_pattern("Luna and the Moon") != vg.title_pattern("How Milo Found His Way")


def test_ayni_baslik_sablonu_arka_arkaya_reddedilir():
    """Sınır 3. Üç kez arka arkaya kullanıldıysa dördüncü reddedilir."""
    for i, (script, sb) in enumerate([
        (SCRIPT_MOON, STORYBOARD_A),
        (SCRIPT_RIVER, STORYBOARD_B),
        (
            "A fox found a lantern in the tall grass and carried it home slowly.",
            {"scenes": [{"duration_seconds": 200, "transition": "cut"}]},
        ),
    ]):
        _publish("bedtime", script, sb, f"Name{i} and the Thing{i}", [f"as{i}"], f"v{i}")

    verdict = vg.evaluate(
        "bedtime",
        "A quiet turtle walked along the shoreline counting shells until dusk fell.",
        {"scenes": [
            {"duration_seconds": 300, "transition": "wipe"},
            {"duration_seconds": 100, "transition": "cut"},
        ]},
        "Tessa and the Shore",
        ["fresh1", "fresh2"],
        "new_voice",
    )

    assert not verdict.passed
    assert any(c.axis == "başlık" for c in verdict.failures)


# --------------------------------------------------------------------------
# Görsel ekseni
# --------------------------------------------------------------------------

def test_ayni_asset_kombinasyonu_reddedilir():
    _publish("bedtime", SCRIPT_MOON, STORYBOARD_A, "Luna and the Moon",
             ["owl", "forest", "pond", "moon"], "af_bella")

    verdict = vg.evaluate(
        "bedtime", SCRIPT_RIVER, STORYBOARD_B, "How Milo Found His Way",
        ["owl", "forest", "pond", "moon"], "am_michael",
    )

    assert not verdict.passed
    assert any(c.axis == "görsel" for c in verdict.failures)


def test_kismi_asset_ortusmesi_gecer():
    """Bir asset paylaşmak sorun değil — eşik 0.60 Jaccard."""
    _publish("bedtime", SCRIPT_MOON, STORYBOARD_A, "Luna and the Moon",
             ["owl", "forest", "pond", "moon"], "af_bella")

    verdict = vg.evaluate(
        "bedtime", SCRIPT_RIVER, STORYBOARD_B, "How Milo Found His Way",
        ["badger", "river", "heron", "raft", "forest"], "am_michael",
    )

    assert verdict.passed, verdict.reason


# --------------------------------------------------------------------------
# Ses ekseni
# --------------------------------------------------------------------------

def test_ayni_ses_arka_arkaya_reddedilir():
    """Sınır 4."""
    scripts = [
        "One rabbit hopped across the meadow and found a warm burrow to rest in.",
        "Two deer walked between tall pines while snow settled on the branches.",
        "Three fireflies drifted above the pond and blinked in slow patterns.",
        "Four sleepy bears curled together in a cave as the winter wind passed.",
    ]
    for i, script in enumerate(scripts):
        sb = {"scenes": [{"duration_seconds": 50 + i * 30, "transition": "cut"}]}
        _publish("bedtime", script, sb, f"Title{i} number {i}", [f"unique{i}"], "af_bella")

    verdict = vg.evaluate(
        "bedtime",
        "A lone heron stood in shallow water watching the last light leave the sky.",
        {"scenes": [
            {"duration_seconds": 400, "transition": "fade"},
            {"duration_seconds": 90, "transition": "wipe"},
        ]},
        "The heron waits for evening",
        ["heron_new", "shallow_water"],
        "af_bella",
    )

    assert not verdict.passed
    assert any(c.axis == "ses" for c in verdict.failures)


# --------------------------------------------------------------------------
# enforce() davranışı
# --------------------------------------------------------------------------

def test_enforce_reddedilen_isi_silmez_kuyruğa_dusurur():
    """Reddedilen iş SİLİNMEZ — attempt artar, yeniden üretim kuyruğunda kalır."""
    _publish("bedtime", SCRIPT_MOON, STORYBOARD_A, "Luna and the Moon", ["a", "b"], "af_bella")

    job = db.create_job("bedtime", "episode")
    verdict = vg.enforce(job, "bedtime", SCRIPT_MOON, STORYBOARD_A,
                         "Luna and the Moon", ["a", "b"], "af_bella")

    assert not verdict.passed
    row = db.get_job(job)
    assert row is not None, "iş silinmemeli"
    assert row["status"] == db.JobStatus.REJECTED.value
    assert row["attempt"] == 2
    assert "VARYASYON" in row["rejection_reason"]


def test_enforce_gecen_isi_dokunmaz():
    job = db.create_job("bedtime", "episode")
    verdict = vg.enforce(job, "bedtime", SCRIPT_MOON, STORYBOARD_A,
                         "Luna and the Moon", ["a", "b"], "af_bella")

    assert verdict.passed
    row = db.get_job(job)
    assert row["status"] == db.JobStatus.QUEUED.value
    assert row["attempt"] == 1


def test_gecmemis_is_parmak_izi_birakmaz():
    """Yayınlanmamış denemeler geçmişi kirletmemeli."""
    job = db.create_job("bedtime", "episode")
    vg.enforce(job, "bedtime", SCRIPT_MOON, STORYBOARD_A, "Luna and the Moon", ["a"], "af_bella")

    assert db.recent_fingerprints("bedtime") == []
