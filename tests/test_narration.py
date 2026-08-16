"""Seslendirme aşaması testleri — Kokoro çalıştırmadan.

Kritik davranış: sahne süreleri senaryo TAHMİNİYLE değil, GERÇEK ses uzunluğuyla
güncellenmeli. Duman testinde senaryo 66 sn tahmin ederken gerçek anlatım 32.5 sn
çıktı; güncelleme olmasaydı video 33 saniye sessizlikle uzardı.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from core import config, narration, voice


class FakeNarration:
    """voice.synthesize dönüşünü taklit eder."""

    def __init__(self, seconds: float, path: Path):
        self.duration_seconds = seconds
        self.audio_path = path
        self.voice_id = "af_bella"
        self.sample_rate = config.TTS_SAMPLE_RATE


@pytest.fixture
def fake_synth(monkeypatch, tmp_path):
    """Gerçek TTS yerine, metin uzunluğuyla orantılı sahte süre üretir."""
    monkeypatch.setattr(config, "CACHE_DIR", tmp_path / "cache")

    calls: list[dict] = []

    def _synth(text, voice_id, speech_rate, out_path, **kw):
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_bytes(b"RIFF fake wav")
        seconds = len(text.split()) / 2.75  # ~165 kelime/dk
        calls.append({"text": text, "voice_id": voice_id, "rate": speech_rate})
        return FakeNarration(seconds, out_path)

    monkeypatch.setattr(voice, "synthesize", _synth)
    return calls


def _board(narrations: list[str]) -> dict:
    return {
        "premise": {"channel": "bedtime"},
        "title": "T",
        "scenes": [
            {
                "index": i,
                "narration": n,
                "setting": "mossy stream",
                "action": "walks",
                "mood": "calm",
                "duration_seconds": 999,  # kasıtlı yanlış tahmin
                "transition": "fade",
                "assets": {"background": "bg/x/soft", "character": "char/y/walking"},
            }
            for i, n in enumerate(narrations)
        ],
    }


# --------------------------------------------------------------------------
# Süre güncellemesi — asıl mesele
# --------------------------------------------------------------------------

def test_sahne_sureleri_gercek_sesle_degistirilir(fake_synth):
    board = _board(["one two three four five six " * 5, "short line here"])

    result = narration.narrate(1, board, config.Channel.BEDTIME)

    süreler = [s["duration_seconds"] for s in result.storyboard["scenes"]]
    assert 999 not in süreler, "senaryo tahmini olduğu gibi kalmış"
    assert süreler[0] > süreler[1], "uzun metin daha uzun sahne vermeli"


def test_nefes_payi_eklenir(fake_synth):
    """Anlatım bitince sahne hemen kesilmemeli."""
    board = _board(["one two three four five six seven eight nine ten eleven"])

    result = narration.narrate(1, board, config.Channel.BEDTIME)

    ham = 11 / 2.75
    beklenen = ham + narration.LEAD_IN_SECONDS + narration.LEAD_OUT_SECONDS
    assert result.storyboard["scenes"][0]["duration_seconds"] == round(beklenen)


def test_ses_gecikmesi_yazilir(fake_synth):
    board = _board(["a b c d e f"])
    result = narration.narrate(1, board, config.Channel.BEDTIME)

    assert result.storyboard["scenes"][0]["audioDelaySeconds"] == narration.LEAD_IN_SECONDS


def test_toplam_sure_sahnelerin_toplami(fake_synth):
    board = _board(["one two three " * 4, "four five six " * 3, "seven eight " * 5])
    result = narration.narrate(1, board, config.Channel.BEDTIME)

    toplam = sum(s["duration_seconds"] for s in result.storyboard["scenes"])
    assert abs(result.total_seconds - toplam) < 2.0


# --------------------------------------------------------------------------
# Dosya yönetimi
# --------------------------------------------------------------------------

def test_audio_src_mutlak_yol_degil_dosya_adi(fake_synth):
    """Remotion `--public-dir` ile klasörü alır; mutlak yol staticFile'ı bozar."""
    board = _board(["a b c", "d e f"])
    result = narration.narrate(7, board, config.Channel.BEDTIME)

    for i, s in enumerate(result.storyboard["scenes"]):
        assert s["audioSrc"] == f"scene_{i}.wav"
        assert "/" not in s["audioSrc"] and "\\" not in s["audioSrc"]


def test_wav_dosyalari_yazilir(fake_synth):
    board = _board(["a b c", "d e f"])
    result = narration.narrate(7, board, config.Channel.BEDTIME)

    for s in result.storyboard["scenes"]:
        assert (result.audio_dir / s["audioSrc"]).exists()


def test_yeniden_uretimde_eski_dosyalar_temizlenir(fake_synth):
    """Sahne sayısı azalırsa artakalan wav'lar yanlış bölüme karışırdı."""
    narration.narrate(9, _board(["a b", "c d", "e f", "g h"]), config.Channel.BEDTIME)
    result = narration.narrate(9, _board(["a b", "c d"]), config.Channel.BEDTIME)

    kalanlar = sorted(p.name for p in result.audio_dir.glob("*.wav"))
    assert kalanlar == ["scene_0.wav", "scene_1.wav"]


def test_bos_anlatim_sessiz_sahne_uretir(fake_synth):
    board = _board(["a b c", "   "])
    result = narration.narrate(1, board, config.Channel.BEDTIME)

    sessiz = result.storyboard["scenes"][1]
    assert sessiz["audioSrc"] is None
    assert sessiz["duration_seconds"] == int(narration.SILENT_SCENE_SECONDS)


def test_kanal_tempolari_farkli_gecer(fake_synth):
    """Bedtime yavaş okunur; speech_rate sentezleyiciye geçmeli."""
    narration.narrate(1, _board(["a b c"]), config.Channel.BEDTIME)
    assert fake_synth[0]["rate"] == config.CHANNELS[config.Channel.BEDTIME].speech_rate


# --------------------------------------------------------------------------
# Ses seçimi — varyasyon kapısının ses ekseni
# --------------------------------------------------------------------------

def test_ses_havuzdan_secilir(fake_synth):
    result = narration.narrate(1, _board(["a b c"]), config.Channel.BEDTIME)
    assert result.voice_id in voice.BEDTIME_VOICES


def test_ayni_ses_seri_sinira_dayaninca_degisir():
    """Kapı sınırı 4; hep aynı sesi göndermek hattı kilitlerdi."""
    limit = config.VARIATION_MAX_VOICE_STREAK
    geçmiş = ["af_bella"] * limit

    seçim = voice.pick_voice(config.Channel.BEDTIME, geçmiş)

    assert seçim != "af_bella"
    assert seçim in voice.BEDTIME_VOICES


def test_kisa_seride_ses_korunur():
    seçim = voice.pick_voice(config.Channel.BEDTIME, ["af_bella", "af_nicole"])
    assert seçim == "af_bella"


def test_bos_gecmiste_havuzdan_secer():
    assert voice.pick_voice(config.Channel.BEDTIME, []) in voice.BEDTIME_VOICES


def test_ses_secimi_kapinin_esigini_asmaz():
    """Sürekli üretimde ses ekseni hiç tetiklenmemeli."""
    limit = config.VARIATION_MAX_VOICE_STREAK
    geçmiş: list[str] = []

    for _ in range(30):
        v = voice.pick_voice(config.Channel.BEDTIME, geçmiş)
        geçmiş.insert(0, v)

        seri = 0
        for x in geçmiş:
            if x == geçmiş[0]:
                seri += 1
            else:
                break
        assert seri < limit, f"ses serisi {seri}, sınır {limit}: {geçmiş[:8]}"
