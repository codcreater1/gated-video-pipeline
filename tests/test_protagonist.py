"""Kahraman/misafir tasarımının testleri.

Kanal A'nın markası tekrar eden bir karaktere (Fen) dayanıyor, ama varyasyon
kapısı tekrarı cezalandırıyor. Bu ikisi doğru ayrılmazsa ya marka sürekliliği
kaybolur ya da kapı her bölümü reddederek hattı kilitler.
"""

from __future__ import annotations

import random

from core import config, ideation, storyboard


def _premise(seed: int) -> ideation.Premise:
    return ideation.generate(config.Channel.BEDTIME, rng=random.Random(seed))


def _board(premise: ideation.Premise, actions: list[str] | None = None) -> dict:
    """storyboard.build'i script.Episode kurmadan taklit eder."""
    acts = actions or ["walks to the water", "looks around", "rests on a stone"]
    return {
        "premise": premise.to_dict(),
        "title": "T",
        "description": "D",
        "scenes": [
            {
                "index": i,
                "narration": "n",
                "setting": premise.setting,
                "action": a,
                "mood": "calm",
                "duration_seconds": 60,
                "transition": "fade",
                "assets": {
                    "background": storyboard._background_id(premise.setting, "calm"),
                    "character": storyboard._character_id(
                        ideation.PROTAGONIST["species"], a
                    ),
                    "companion": storyboard._character_id(premise.character, a),
                },
            }
            for i, a in enumerate(acts)
        ],
    }


# --------------------------------------------------------------------------
# Kahraman sabit
# --------------------------------------------------------------------------

def test_kahraman_her_bolumde_ayni():
    for seed in range(20):
        p = _premise(seed)
        assert p.protagonist == "Fen"
        assert p.to_dict()["protagonist"] == "Fen"


def test_misafir_havuzda_kahraman_yok():
    """Fen misafir olarak seçilirse kendi kendine misafir olurdu."""
    assert ideation.PROTAGONIST["species"] not in ideation.BEDTIME_COMPANIONS


def test_misafir_bolumden_bolume_degisir():
    misafirler = {_premise(s).character for s in range(25)}
    assert len(misafirler) > 5, f"misafir çeşitliliği çok düşük: {misafirler}"


def test_ozet_iki_karakteri_de_anar():
    p = _premise(3)
    s = p.summary()
    assert "Fen" in s
    assert p.character in s


# --------------------------------------------------------------------------
# Varyasyon kapısı kahramanı saymamalı
# --------------------------------------------------------------------------

def test_varyasyon_listesi_kahramani_dislar():
    """KRİTİK: kahraman sayılsaydı her bölüm örtüşme eşiğini aşardı."""
    board = _board(_premise(1))

    hepsi = storyboard.asset_ids(board)
    varyasyon = storyboard.variation_asset_ids(board)

    kahraman_kimlikleri = [a for a in hepsi if "su_samuru" in a]
    assert kahraman_kimlikleri, "kahraman asset'i üretilmemiş"
    assert not any("su_samuru" in a for a in varyasyon), (
        f"kahraman varyasyon listesine sızmış: {varyasyon}"
    )


def test_varyasyon_listesi_misafiri_ve_arkaplani_icerir():
    p = _premise(1)
    varyasyon = storyboard.variation_asset_ids(_board(p))

    assert any(a.startswith("bg/") for a in varyasyon)
    assert any(a.startswith("char/") for a in varyasyon), "misafir eksik"


def test_farkli_misafirler_dusuk_ortusme_verir():
    """İki bölüm aynı mekânı paylaşsa bile misafir farkı ayırt edici olmalı."""
    a = _premise(2)
    b = _premise(7)
    if a.character == b.character:
        return  # aynı misafir çıktıysa bu testin söyleyeceği bir şey yok

    sa = set(storyboard.variation_asset_ids(_board(a)))
    sb = set(storyboard.variation_asset_ids(_board(b)))
    jaccard = len(sa & sb) / len(sa | sb)

    assert jaccard <= config.VARIATION_MAX_ASSET_OVERLAP, (
        f"örtüşme {jaccard:.2f}, eşik {config.VARIATION_MAX_ASSET_OVERLAP}"
    )


def test_ayni_premise_ayni_kimlikleri_uretir():
    p = _premise(5)
    assert storyboard.variation_asset_ids(_board(p)) == storyboard.variation_asset_ids(
        _board(p)
    )


# --------------------------------------------------------------------------
# Slug — Türkçe karakterler
# --------------------------------------------------------------------------

def test_slug_turkce_karakterleri_korur():
    """Render tarafı tür adından siluet türetiyor; bilgi kaybı yanlış görsel demek."""
    assert storyboard._slug("uzun bacaklı balıkçıl") == "uzun_bacakli_balikcil"
    assert storyboard._slug("küçük baykuş") == "kucuk_baykus"
    assert storyboard._slug("sakin kaplumbağa") == "sakin_kaplumbaga"
    assert storyboard._slug("yaşlı kirpi") == "yasli_kirpi"
    assert storyboard._slug("gri kaz") == "gri_kaz"


def test_slug_bilgi_kaybetmez():
    """Hiçbir misafir adı boş veya birbirine eşit slug üretmemeli."""
    sluglar = [storyboard._slug(c) for c in ideation.BEDTIME_COMPANIONS]

    assert all(s and s != "unknown" for s in sluglar)
    assert len(set(sluglar)) == len(sluglar), "iki misafir aynı slug'a düşüyor"
    assert not any("__" in s for s in sluglar), f"bozuk slug: {sluglar}"


def test_mekan_sluglari_da_saglam():
    sluglar = [storyboard._slug(s) for s in ideation.BEDTIME_SETTINGS]
    assert len(set(sluglar)) == len(sluglar)
    assert all(s and "__" not in s for s in sluglar)
