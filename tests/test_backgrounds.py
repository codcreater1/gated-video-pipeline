"""Diller arası kapsama — Python havuzları ile Remotion render'ı senkron mu?

Asset kimlikleri Python'da üretiliyor (`storyboard._slug`), render tarafında
TypeScript anahtar tablolarıyla çözülüyor. İki tarafın ayrı repo dosyalarında
yaşaması sessiz bir hata sınıfı yaratıyor: havuza yeni bir mekân eklenir,
render tarafına eklenmez, ve o mekân sessizce varsayılan araziye düşer.

Bunun neden ciddi olduğu: varyasyon kapısının görsel ekseni `bg/...`
kimliklerini karşılaştırıyor. Kimlikler farklıysa kapı "çeşitlilik var" der.
Ama ekranda iki bölüm de aynı görünüyorsa, kapı var olmayan bir şeyi ölçmüş
olur — ve tam olarak bu, bir süre gerçekten böyleydi: `SceneView` arka plan
kimliğini hiç okumuyordu.

Bu testler TypeScript kaynağını okuyup eşleme mantığını taklit eder. Kırılgan
görünebilir ama alternatifi yok: iki dilin ortak sözleşmesini derleyici
denetleyemiyor.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from core import config, ideation, storyboard

REMOTION = config.REPO_ROOT / "remotion" / "src"
TERRAIN_TS = REMOTION / "backgrounds" / "terrain.ts"
COMPANION_TSX = REMOTION / "characters" / "Companion.tsx"

# ["ad", ["anahtar", "anahtar"]] biçimindeki tablo satırları
_ROW = re.compile(r'\[\s*"(\w+)"\s*,\s*\[([^\]]*)\]\s*\]')


def _parse_table(source: Path, const_name: str) -> list[tuple[str, list[str]]]:
    """TS'teki anahtar tablosunu (sırasını koruyarak) okur."""
    text = source.read_text(encoding="utf-8")
    start = text.index(const_name)
    body = text[start : text.index("];", start)]
    return [
        (name, re.findall(r'"([^"]+)"', keys))
        for name, keys in _ROW.findall(body)
    ]


def _match(slug: str, table: list[tuple[str, list[str]]]) -> str | None:
    """TS tarafındaki eşleme mantığının aynısı: sıralı, alt dize."""
    for name, keys in table:
        if any(k in slug for k in keys):
            return name
    return None


@pytest.fixture(scope="module")
def terrains() -> list[tuple[str, list[str]]]:
    return _parse_table(TERRAIN_TS, "TERRAIN_KEYWORDS")


@pytest.fixture(scope="module")
def families() -> list[tuple[str, list[str]]]:
    return _parse_table(COMPANION_TSX, "FAMILY_KEYWORDS")


# --------------------------------------------------------------------------
# Tablolar okunabiliyor mu
# --------------------------------------------------------------------------

def test_ts_tablolari_okunabiliyor(terrains, families):
    """Bu test kırılırsa aşağıdakilerin hepsi yanlış sebeple yeşil geçerdi."""
    assert len(terrains) >= 10, f"arazi tablosu okunamadı: {terrains}"
    assert len(families) >= 4, f"aile tablosu okunamadı: {families}"


# --------------------------------------------------------------------------
# Mekânlar
# --------------------------------------------------------------------------

def test_her_mekan_bir_araziye_esleniyor(terrains):
    """Eşlenmeyen mekân sessizce varsayılana düşer — asıl yakalanan hata bu."""
    eksik = [
        s for s in ideation.BEDTIME_SETTINGS
        if _match(storyboard._slug(s), terrains) is None
    ]
    assert not eksik, (
        f"şu mekânların render karşılığı yok: {eksik}. "
        f"remotion/src/backgrounds/terrain.ts içindeki TERRAIN_KEYWORDS'e ekle."
    )


def test_her_mekan_ayri_arazi_uretir(terrains):
    """KRİTİK: iki mekân aynı araziye düşerse ekranda ayırt edilemezler.

    Varyasyon kapısı kimlikler farklı olduğu için "çeşitlilik var" demeye
    devam eder, ama izleyici aynı videoyu iki kez görür — inauthentic content
    politikasının tarif ettiği durumun ta kendisi.
    """
    eslesme: dict[str, list[str]] = {}
    for setting in ideation.BEDTIME_SETTINGS:
        terrain = _match(storyboard._slug(setting), terrains)
        eslesme.setdefault(str(terrain), []).append(setting)

    cakisan = {t: ss for t, ss in eslesme.items() if len(ss) > 1}
    assert not cakisan, f"aynı araziyi paylaşan mekânlar: {cakisan}"


def test_karli_orman_sirasi_dogru(terrains):
    """`kar_altinda_cam_ormani` hem "kar" hem "orman" içeriyor.

    Sıra bozulursa karlı orman sıradan ormana düşer ve kar tamamen kaybolur —
    tabloda sıranın neden önemli olduğunun somut kanıtı.
    """
    assert _match("kar_altinda_cam_ormani", terrains) == "snow"
    assert _match("sessiz_orman", terrains) == "conifer"


def test_dere_ve_gol_ayri_arazi(terrains):
    """İkisi de su ama görsel olarak ayrı: biri dar dere, diğeri geniş göl."""
    assert _match("yosunlu_dere_yatagi", terrains) == "stream"
    assert _match("ay_isiginda_gol_kiyisi", terrains) == "lake"


# --------------------------------------------------------------------------
# Misafirler
# --------------------------------------------------------------------------

def test_her_misafir_bir_aileye_esleniyor(families):
    """Eşlenmeyen misafir "rounded" varsayılanına düşer.

    İlk sürümde siluet tamamen hash'ten türetiliyordu ve balıkçıl uzun
    kulaklı bir tavşan olarak çiziliyordu (bkz. Companion.tsx).
    """
    eksik = [
        c for c in ideation.BEDTIME_COMPANIONS
        if _match(storyboard._slug(c), families) is None
    ]
    assert not eksik, (
        f"şu misafirlerin aile karşılığı yok: {eksik}. "
        f"remotion/src/characters/Companion.tsx içindeki FAMILY_KEYWORDS'e ekle."
    )


def test_kuslar_kus_ailesinde(families):
    """Gaga ve uzun bacak buna bağlı; yanlış aile doğrudan yanlış hayvan."""
    for kus in ("uzun bacaklı balıkçıl", "küçük baykuş", "gri kaz", "beyaz güvercin"):
        assert _match(storyboard._slug(kus), families) == "bird", kus


def test_aile_havuzu_gercekten_kullaniliyor(families):
    """Tanımlı ama hiçbir misafirin düşmediği aile, ölü kod demek."""
    kullanilan = {
        _match(storyboard._slug(c), families) for c in ideation.BEDTIME_COMPANIONS
    }
    tanimli = {name for name, _ in families}
    assert tanimli <= kullanilan, f"hiç kullanılmayan aile: {tanimli - kullanilan}"


# --------------------------------------------------------------------------
# Varyantlar
# --------------------------------------------------------------------------

def test_ruh_hali_varyantlari_ts_tarafinda_taniniyor():
    """`storyboard.MOOD_VARIANTS` çıktısı TS'teki VARIANTS listesiyle eşleşmeli.

    Tanınmayan varyant sessizce "soft"a düşer ve atmosfer farkı kaybolur.
    """
    text = TERRAIN_TS.read_text(encoding="utf-8")
    block = text[text.index("VARIANTS:") : text.index("];", text.index("VARIANTS:"))]
    ts_variants = set(re.findall(r'"(\w+)"', block))

    py_variants = set(storyboard.MOOD_VARIANTS.values()) | {storyboard.DEFAULT_VARIANT}
    assert py_variants <= ts_variants, (
        f"TS tarafında tanınmayan varyant: {py_variants - ts_variants}"
    )


def test_uretilen_kimlik_bicimi_ts_ayristiricisiyla_uyumlu():
    """`bg/<mekân>/<varyant>` — TS `split('/')[1]` ve `[2]` okuyor."""
    asset_id = storyboard._background_id("bambu korusu", "calm")
    parts = asset_id.split("/")

    assert parts[0] == "bg"
    assert parts[1] == "bambu_korusu"
    assert parts[2] == storyboard.MOOD_VARIANTS["calm"]
    assert len(parts) == 3, "fazladan bölüm TS ayrıştırıcısını kaydırır"
