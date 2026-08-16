"""YAYIN — hattın son adımı ve dışa dönük tek yazma işlemi.

Buraya kadar her şey geri alınabilir: reddedilen iş kuyruğa döner, başarısız
render tekrarlanır. Yükleme geri alınamaz — video bir kez YouTube'a gittiğinde
kanalın politika yüzeyine dahil olur. O yüzden bu modül üretmez, yalnızca
zaten onaylanmış bir dosyayı taşır ve yolda üç şeyi bir daha denetler.

Neden burada TEKRAR denetim var:

- **Onay.** `approval.assert_publishable()` çağrılmak ZORUNDA (bkz. approval.py).
  Bu modülün var oluş nedeni o kapıyı geçmek değil, ona uymak.
- **Günlük tavan.** `pipeline.check_cadence` işi ÜRETİRKEN denetler. Ama onaylı
  işler kuyrukta birikir; beş onaylı videoyu aynı gün yayınlamak tavanı deler.
  Tavanın asıl anlamı "günde kaç video ÜRETİLDİ" değil, "günde kaç video
  YAYINLANDI" — o yüzden asıl denetim yeri burası.
- **Made for Kids.** `config.validate()` bunu yapılandırma seviyesinde tutuyor,
  ama API'ye giden gerçek değer burada oluşuyor. Yanlış bayrak FTC/COPPA
  sorumluluğu doğurur ve bir kez yüklendikten sonra düzeltmek kanal geçmişini
  temizlemiyor. Bkz. docs/content-guidelines.md §1.

Parmak izi yayın anında yazılır (`variation_guard.commit_fingerprint`), üretim
anında değil — yayınlanmamış denemeler varyasyon geçmişini kirletmemeli.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

from core import approval, config, db, storyboard, variation_guard

# Yalnızca yükleme yetkisi. Okuma/analytics ayrı bir scope ve ayrı bir onay
# ekranı ister; kullanıcıdan ihtiyacımız olmayan yetkiyi istemiyoruz.
SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]

# 1 = Film & Animation. Çocuk animasyonu için doğru kategori; 24 (Entertainment)
# daha genel ve öneri sinyalini zayıflatıyor.
CATEGORY_FILM_ANIMATION = "1"

# YouTube auto-dubbing bu alan dolu değilse çalışmıyor. Kanalın 27 dile
# açılması buna bakıyor — boş bırakmak sessizce tüm çeviri planını iptal eder.
AUDIO_LANGUAGE = "en"

# 4 MB'lık parçalar. Tek parça yükleme 40 MB'lık bir bölümde koptuğunda
# baştan başlamak gerekiyor; resumable upload kaldığı yerden devam eder.
UPLOAD_CHUNK_BYTES = 4 * 1024 * 1024

# Geçici sunucu hataları. Bunlarda üstel geri çekilme ile tekrar denenir.
RETRIABLE_STATUS = frozenset({500, 502, 503, 504})
MAX_RETRIES = 5


class PublishError(Exception):
    """Yükleme yapılamadı."""


class NotAuthorized(PublishError):
    """Kanal için OAuth token yok veya yenilenemiyor."""


class DailyCapReached(PublishError):
    """Bugünün yayın tavanı doldu."""


class MisclassificationError(PublishError):
    """Made for Kids bayrağı hedef yaşla çelişiyor — yükleme yapılmaz."""


@dataclass
class PublishResult:
    job_id: int
    youtube_video_id: str
    title: str
    channel: str
    made_for_kids: bool
    privacy_status: str

    @property
    def url(self) -> str:
        return f"https://www.youtube.com/watch?v={self.youtube_video_id}"


class Uploader(Protocol):
    """Yükleyici. Testlerde sahte bir yükleyiciyle değiştirilebilir —
    böylece kapı mantığı Google API'sine dokunmadan doğrulanır."""

    def __call__(
        self, channel: config.Channel, video_path: Path, metadata: dict[str, Any]
    ) -> str: ...


# --------------------------------------------------------------------------
# Kimlik doğrulama
# --------------------------------------------------------------------------

def token_path(channel: config.Channel) -> Path:
    """Kanalın OAuth token dosyası.

    .env'deki değişken doluysa o kazanır; yoksa veri kökündeki credentials
    dizini. Her iki durumda da repo dışında — token'ın yanlışlıkla commit'lenmesi
    mümkün olmamalı.
    """
    override = os.getenv(config.CHANNELS[channel].token_file_env)
    if override and override.strip():
        return Path(override.strip())
    return config.CREDENTIALS_DIR / f"{channel.value}_token.json"


def authorized(channel: config.Channel) -> bool:
    return token_path(channel).exists()


def _require_google() -> None:
    """Google istemcisi kurulu mu?

    `google-*` paketleri [runtime] extra'sında — çekirdek mantığı ve kapıları
    test etmek için gerekmiyorlar. Kurulu değilken ham bir ModuleNotFoundError
    fırlatmak, kullanıcıya neyi eksik kurduğunu söylemiyor.
    """
    from importlib.util import find_spec

    missing = [
        name
        for name in ("googleapiclient", "google.oauth2", "google_auth_oauthlib")
        if find_spec(name) is None
    ]
    if missing:
        raise PublishError(
            f"YouTube istemcisi kurulu değil (eksik: {', '.join(missing)}).\n"
            f'Şunu çalıştır: uv pip install -e ".[runtime]"'
        )


def authorize(channel: config.Channel) -> Path:
    """Tarayıcı açar, kanalı yetkilendirir ve token'ı diske yazar.

    Kanal başına bir kez çalıştırılır. Yanlış Google hesabıyla giriş yapmak en
    yaygın hata — tarayıcıda hangi kanalın yetkilendirildiği kontrol edilmeli.
    """
    secret = os.getenv("YT_CLIENT_SECRET_FILE", "").strip()
    if not secret:
        raise NotAuthorized(
            "YT_CLIENT_SECRET_FILE tanımlı değil. Google Cloud Console'dan "
            "OAuth 2.0 Client ID (Desktop app) JSON'unu indirip .env'de bu "
            "değişkene yolunu yaz. Bkz. docs/setup.md Adım 5."
        )
    if not Path(secret).exists():
        raise NotAuthorized(f"Client secret dosyası bulunamadı: {secret}")

    _require_google()
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(secret, SCOPES)
    creds = flow.run_local_server(port=0)

    target = token_path(channel)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(creds.to_json(), encoding="utf-8")
    return target


def _service(channel: config.Channel):
    """Yetkilendirilmiş YouTube istemcisi. Süresi dolmuş token'ı yeniler.

    Token denetimi import'lardan ÖNCE: eksik yetkilendirme, eksik paketten
    çok daha yaygın bir durum ve kullanıcının önce göreceği hata o olmalı.
    """
    path = token_path(channel)
    if not path.exists():
        raise NotAuthorized(
            f"{channel.value} kanalı yetkilendirilmemiş (beklenen: {path}).\n"
            f"Şunu çalıştır: otomasyon authorize {channel.value}"
        )

    _require_google()
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    creds = Credentials.from_authorized_user_file(str(path), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            path.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise NotAuthorized(
                f"{channel.value} token'ı geçersiz ve yenilenemiyor. "
                f"Yeniden yetkilendir: otomasyon authorize {channel.value}"
            )

    # cache_discovery=False: discovery önbelleği oauth2client istiyor ve yoksa
    # her çağrıda gürültülü bir uyarı basıyor.
    return build("youtube", "v3", credentials=creds, cache_discovery=False)


# --------------------------------------------------------------------------
# Meta veri
# --------------------------------------------------------------------------

def _tags(job: dict[str, Any], board: dict[str, Any]) -> list[str]:
    """Sabit kanal etiketleri + bölümün kendi ekseni.

    Etiketler öneri sinyalinin küçük bir parçası; asıl iş başlık ve retention'da.
    Uzun etiket listeleri 2026'da spam sinyali sayılıyor, o yüzden kısa tutuluyor.
    """
    premise = board.get("premise", {})
    base = ["bedtime stories", "kids stories", "calm", "sleep"]
    extra = [
        str(premise.get("protagonist", "")).lower(),
        str(premise.get("character", "")).lower(),
        str(premise.get("setting", "")).lower(),
    ]
    seen: set[str] = set()
    out: list[str] = []
    for t in base + extra:
        t = t.strip()
        if t and t not in seen:
            seen.add(t)
            out.append(t)
    return out[:10]


def build_metadata(
    job: dict[str, Any],
    profile: config.ChannelProfile,
    privacy_status: str = "public",
) -> dict[str, Any]:
    """videos.insert gövdesini kurar.

    `selfDeclaredMadeForKids` yazılabilir alan; `madeForKids` salt okunur ve
    YouTube tarafından türetiliyor. Yanlış olanı göndermek bayrağı sessizce
    ayarlanmamış bırakır.
    """
    board = json.loads(job["storyboard_json"] or "{}")

    return {
        "snippet": {
            "title": (job["title"] or "").strip()[:100],
            "description": (board.get("description") or "").strip()[:5000],
            "tags": _tags(job, board),
            "categoryId": CATEGORY_FILM_ANIMATION,
            "defaultLanguage": AUDIO_LANGUAGE,
            # auto-dubbing bu alana bakar
            "defaultAudioLanguage": AUDIO_LANGUAGE,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": profile.made_for_kids,
            "license": "youtube",
            "embeddable": True,
        },
    }


def _assert_classification(profile: config.ChannelProfile) -> None:
    """Son sınıflandırma denetimi — API çağrısından hemen önce.

    config.validate() aynı kuralı yapılandırma seviyesinde tutuyor. Bu ikinci
    denetim, aradaki kodun (veya birinin monkeypatch'inin) bayrağı çevirmiş
    olma ihtimaline karşı. Yanlış yüklenmiş bir videoyu düzeltmek mümkün ama
    kanalın geçmişini temizlemiyor.
    """
    upper_age = int(profile.age_range.split("-")[-1])
    if upper_age < 13 and not profile.made_for_kids:
        raise MisclassificationError(
            f"{profile.channel.value}: hedef yaş {profile.age_range} (13 altı) ama "
            f"made_for_kids=False. Bu yanlış sınıflandırmadır ve FTC/COPPA "
            f"sorumluluğu doğurur. Yükleme yapılmadı."
        )


# --------------------------------------------------------------------------
# Yükleme
# --------------------------------------------------------------------------

def _youtube_upload(
    channel: config.Channel, video_path: Path, metadata: dict[str, Any]
) -> str:
    """Gerçek yükleme — resumable, geçici hatalarda üstel geri çekilme."""
    # Önce servis: yetkilendirme ve paket denetimleri orada, net hatalarla.
    service = _service(channel)

    from googleapiclient.errors import HttpError
    from googleapiclient.http import MediaFileUpload

    media = MediaFileUpload(
        str(video_path),
        chunksize=UPLOAD_CHUNK_BYTES,
        resumable=True,
        mimetype="video/mp4",
    )
    request = service.videos().insert(
        part="snippet,status", body=metadata, media_body=media
    )

    response = None
    attempt = 0
    while response is None:
        try:
            _, response = request.next_chunk()
        except HttpError as exc:
            if exc.resp.status not in RETRIABLE_STATUS or attempt >= MAX_RETRIES:
                raise PublishError(f"YouTube {exc.resp.status}: {exc}") from exc
            attempt += 1
            # 2, 4, 8, 16, 32 saniye
            time.sleep(2**attempt)

    video_id = response.get("id")
    if not video_id:
        raise PublishError(f"YouTube kimlik döndürmedi: {response}")
    return str(video_id)


def _archive_card(job_id: int, result: PublishResult) -> None:
    """Onay kartını yayınlanmış arşivine taşır ve yayın bilgisini ekler.

    Kart silinmiyor: hangi videonun kim tarafından, ne zaman onaylandığı
    kanal bir politika incelemesine girerse tek kanıt bu.
    """
    src = config.APPROVED_DIR / f"job_{job_id}.json"
    if not src.exists():
        return

    data = json.loads(src.read_text(encoding="utf-8"))
    data["youtube_video_id"] = result.youtube_video_id
    data["youtube_url"] = result.url
    data["privacy_status"] = result.privacy_status
    data["published_at"] = datetime.now(UTC).isoformat()

    config.PUBLISHED_DIR.mkdir(parents=True, exist_ok=True)
    (config.PUBLISHED_DIR / src.name).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    src.unlink()


def check_daily_cap(channel: config.Channel, fmt: str) -> None:
    """Bugün bu formatta kaç video yayınlandı? Tavan doluysa yükleme yapılmaz."""
    cap = (
        config.HARD_DAILY_CAP_SHORTS if fmt == "short" else config.HARD_DAILY_CAP_LONGFORM
    )
    published = db.published_today()
    if published >= cap:
        raise DailyCapReached(
            f"Bugün {published} video yayınlandı, mutlak tavan {cap}. "
            f"İş onaylı kalır ve yarın yayınlanabilir."
        )


def publish(
    job_id: int,
    uploader: Uploader | None = None,
    privacy_status: str = "public",
) -> PublishResult:
    """Onaylanmış bir videoyu YouTube'a yükler.

    Sıra kasıtlı: önce geri alınamaz olmayan her denetim yapılır, sonra yükleme,
    en son durum yazılır. Yükleme koparsa iş APPROVED kalır ve tekrar denenebilir.
    """
    job = db.get_job(job_id)
    if job is None:
        raise ValueError(f"İş bulunamadı: {job_id}")

    if job["youtube_video_id"]:
        raise PublishError(
            f"İş #{job_id} zaten yayınlanmış: {job['youtube_video_id']}. "
            f"Aynı videoyu ikinci kez yüklemek kanalda tekrar sinyali üretir."
        )

    # ⛔ ONAY KAPISI — approval.py bu çağrıyı şart koşuyor.
    approval.assert_publishable(job_id)

    channel = config.Channel(job["channel"])
    profile = config.CHANNELS[channel]

    _assert_classification(profile)
    check_daily_cap(channel, job["format"])

    video_path = Path(job["output_path"] or "")
    if not video_path.exists():
        raise PublishError(
            f"Video dosyası yok: {video_path or '(kayıtlı yol yok)'}. "
            f"İş yayınlanamaz."
        )

    metadata = build_metadata(job, profile, privacy_status=privacy_status)
    video_id = (uploader or _youtube_upload)(channel, video_path, metadata)

    result = PublishResult(
        job_id=job_id,
        youtube_video_id=video_id,
        title=metadata["snippet"]["title"],
        channel=channel.value,
        made_for_kids=profile.made_for_kids,
        privacy_status=privacy_status,
    )

    db.update_job(
        job_id,
        status=db.JobStatus.PUBLISHED.value,
        youtube_video_id=video_id,
        published_at=datetime.now(UTC).isoformat(),
    )

    # Parmak izi ancak şimdi geçmişe girer — yayınlanmamış denemeler varyasyon
    # penceresini kirletmemeli (bkz. variation_guard.enforce).
    board = json.loads(job["storyboard_json"] or "{}")
    variation_guard.commit_fingerprint(
        job_id=job_id,
        channel=channel.value,
        storyboard=board,
        title=job["title"] or "",
        asset_ids=storyboard.variation_asset_ids(board),
        voice_id=job["voice_id"] or profile.voice_id,
    )

    _archive_card(job_id, result)
    return result


def pending_uploads() -> list[dict[str, Any]]:
    """Onaylanmış ama henüz yüklenmemiş işler."""
    return [
        j for j in db.jobs_by_status(db.JobStatus.APPROVED) if not j["youtube_video_id"]
    ]


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def _cli() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="YouTube yayın yardımcıları")
    parser.add_argument(
        "--authorize", metavar="KANAL", help="Kanalı yetkilendir (bedtime | storytime)"
    )
    parser.add_argument("--job", type=int, help="Bu işi yükle")
    parser.add_argument(
        "--privacy", default="public", choices=["public", "unlisted", "private"]
    )
    parser.add_argument("--list", action="store_true", help="Yükleme bekleyenleri listele")
    args = parser.parse_args()

    if args.authorize:
        try:
            channel = config.Channel(args.authorize)
        except ValueError:
            print(f"Bilinmeyen kanal: {args.authorize}")
            return 1
        path = authorize(channel)
        print(f"Yetkilendirildi. Token: {path}")
        return 0

    if args.list:
        jobs = pending_uploads()
        if not jobs:
            print("Yükleme bekleyen iş yok.")
            return 0
        for j in jobs:
            print(f"  #{j['id']:>4}  {j['channel']:<10}  {j['title']}")
        return 0

    if args.job:
        result = publish(args.job, privacy_status=args.privacy)
        print(f"Yayınlandı: {result.url}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
