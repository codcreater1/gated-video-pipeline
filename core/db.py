"""SQLite durum katmanı ve iş kuyruğu.

Postgres gereksiz: tek makine, günde en fazla 4 iş. n8n kendi DB'sini ayrı tutar.
DB harici diskte (D:) yaşar, kod C:'de kalır.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any

from core import config


class JobStatus(StrEnum):
    """İş yaşam döngüsü. Kapılardan dönenler REJECTED olur, silinmez."""

    QUEUED = "queued"
    SCRIPTING = "scripting"
    # Varyasyon kapısı burada çalışır
    STORYBOARDING = "storyboarding"
    GENERATING = "generating"
    RENDERING = "rendering"
    # QC kapısı burada çalışır
    AWAITING_APPROVAL = "awaiting_approval"
    APPROVED = "approved"
    PUBLISHED = "published"
    # Kapılardan dönenler
    REJECTED = "rejected"
    FAILED = "failed"


SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    channel           TEXT    NOT NULL,
    format            TEXT    NOT NULL,
    status            TEXT    NOT NULL,
    topic             TEXT,
    title             TEXT,
    title_pattern     TEXT,
    script            TEXT,
    storyboard_json   TEXT,
    voice_id          TEXT,
    asset_ids_json    TEXT,
    duration_seconds  INTEGER,
    output_path       TEXT,
    youtube_video_id  TEXT,
    cost_usd          REAL    NOT NULL DEFAULT 0.0,
    rejection_reason  TEXT,
    attempt           INTEGER NOT NULL DEFAULT 1,
    created_at        TEXT    NOT NULL,
    updated_at        TEXT    NOT NULL,
    published_at      TEXT
);

CREATE INDEX IF NOT EXISTS idx_jobs_status  ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_channel ON jobs(channel, created_at DESC);

-- Bütçe kapısının denetlediği harcama defteri.
-- Her ücretli çağrı buraya yazılır; job silinse bile kayıt kalır.
CREATE TABLE IF NOT EXISTS spend (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id      INTEGER,
    category    TEXT    NOT NULL,   -- 'llm' | 'ai_video' | 'other'
    detail      TEXT,
    usd         REAL    NOT NULL,
    created_at  TEXT    NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE INDEX IF NOT EXISTS idx_spend_created ON spend(created_at);
CREATE INDEX IF NOT EXISTS idx_spend_job     ON spend(job_id);

-- Varyasyon kapısının geçmişi. Yayınlanmış işlerin parmak izleri.
CREATE TABLE IF NOT EXISTS fingerprints (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id            INTEGER NOT NULL,
    channel           TEXT    NOT NULL,
    script_vector     BLOB,
    structure_hash    TEXT,
    title_pattern     TEXT,
    asset_ids_json    TEXT,
    voice_id          TEXT,
    created_at        TEXT    NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE INDEX IF NOT EXISTS idx_fp_channel ON fingerprints(channel, created_at DESC);

-- Fikir havuzu. Tekrar önleme burada başlar.
CREATE TABLE IF NOT EXISTS topics (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    channel     TEXT    NOT NULL,
    topic       TEXT    NOT NULL,
    used_count  INTEGER NOT NULL DEFAULT 0,
    last_used   TEXT,
    created_at  TEXT    NOT NULL,
    UNIQUE(channel, topic)
);

-- Yayın sonrası performans, ideation'a geri beslenir.
CREATE TABLE IF NOT EXISTS analytics (
    id                   INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id               INTEGER NOT NULL,
    youtube_video_id     TEXT    NOT NULL,
    views                INTEGER,
    avg_view_duration_s  INTEGER,
    retention_pct        REAL,
    fetched_at           TEXT    NOT NULL,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat()


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    """Bağlantı açar, foreign key'leri etkinleştirir, commit/rollback yönetir."""
    config.DB_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    # exFAT üzerinde WAL güvenilir değil; harici disk çıkarılırsa bozulma riski.
    conn.execute("PRAGMA journal_mode = DELETE")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init() -> None:
    """Şemayı oluşturur. Idempotent."""
    with connect() as conn:
        conn.executescript(SCHEMA)


# --------------------------------------------------------------------------
# İş kuyruğu
# --------------------------------------------------------------------------

def create_job(channel: str, fmt: str, topic: str | None = None) -> int:
    ts = _now()
    with connect() as conn:
        cur = conn.execute(
            "INSERT INTO jobs (channel, format, status, topic, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (channel, fmt, JobStatus.QUEUED.value, topic, ts, ts),
        )
        return int(cur.lastrowid)


def get_job(job_id: int) -> dict[str, Any] | None:
    with connect() as conn:
        row = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        return dict(row) if row else None


def update_job(job_id: int, **fields: Any) -> None:
    """İş alanlarını günceller. status geçişleri burada serbest —
    kapı mantığı ilgili modüllerde uygulanır."""
    if not fields:
        return
    fields["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE jobs SET {cols} WHERE id = ?", (*fields.values(), job_id))


def reject_job(job_id: int, reason: str) -> None:
    """Kapıdan dönen işi reddeder. İş SİLİNMEZ — yeniden üretim kuyruğunda kalır."""
    with connect() as conn:
        conn.execute(
            "UPDATE jobs SET status = ?, rejection_reason = ?, attempt = attempt + 1, "
            "updated_at = ? WHERE id = ?",
            (JobStatus.REJECTED.value, reason, _now(), job_id),
        )


def jobs_by_status(status: JobStatus, limit: int = 100) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY created_at ASC LIMIT ?",
            (status.value, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def recent_jobs(channel: str, limit: int = config.VARIATION_LOOKBACK) -> list[dict[str, Any]]:
    """Varyasyon kapısının karşılaştırma penceresi."""
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM jobs WHERE channel = ? AND status IN (?, ?) "
            "ORDER BY created_at DESC LIMIT ?",
            (channel, JobStatus.PUBLISHED.value, JobStatus.APPROVED.value, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def published_today(channel: str | None = None) -> int:
    """Günlük tavan denetimi için. UTC gün sınırı."""
    today = datetime.now(UTC).date().isoformat()
    sql = "SELECT COUNT(*) FROM jobs WHERE status = ? AND published_at LIKE ?"
    params: list[Any] = [JobStatus.PUBLISHED.value, f"{today}%"]
    if channel:
        sql += " AND channel = ?"
        params.append(channel)
    with connect() as conn:
        return int(conn.execute(sql, params).fetchone()[0])


# --------------------------------------------------------------------------
# Harcama defteri
# --------------------------------------------------------------------------

def record_spend(job_id: int | None, category: str, usd: float, detail: str = "") -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO spend (job_id, category, detail, usd, created_at) VALUES (?, ?, ?, ?, ?)",
            (job_id, category, detail, usd, _now()),
        )


def job_spend(job_id: int) -> float:
    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(usd), 0.0) FROM spend WHERE job_id = ?", (job_id,)
        ).fetchone()
        return float(row[0])


def month_spend() -> float:
    month = datetime.now(UTC).strftime("%Y-%m")
    with connect() as conn:
        row = conn.execute(
            "SELECT COALESCE(SUM(usd), 0.0) FROM spend WHERE created_at LIKE ?", (f"{month}%",)
        ).fetchone()
        return float(row[0])


# --------------------------------------------------------------------------
# Varyasyon parmak izleri
# --------------------------------------------------------------------------

def record_fingerprint(
    job_id: int,
    channel: str,
    script_vector: bytes | None,
    structure_hash: str,
    title_pattern: str,
    asset_ids: list[str],
    voice_id: str,
) -> None:
    with connect() as conn:
        conn.execute(
            "INSERT INTO fingerprints "
            "(job_id, channel, script_vector, structure_hash, title_pattern, "
            " asset_ids_json, voice_id, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                job_id, channel, script_vector, structure_hash, title_pattern,
                json.dumps(asset_ids), voice_id, _now(),
            ),
        )


def recent_fingerprints(
    channel: str, limit: int = config.VARIATION_LOOKBACK
) -> list[dict[str, Any]]:
    with connect() as conn:
        rows = conn.execute(
            "SELECT * FROM fingerprints WHERE channel = ? ORDER BY created_at DESC LIMIT ?",
            (channel, limit),
        ).fetchall()
        return [dict(r) for r in rows]


# --------------------------------------------------------------------------
# Yayın sonrası performans
# --------------------------------------------------------------------------

def record_analytics(
    job_id: int,
    youtube_video_id: str,
    views: int,
    avg_view_duration_s: int,
    retention_pct: float,
) -> None:
    """Bir ölçüm anını yazar.

    Güncelleme değil ekleme: aynı video için birden çok satır birikir ve
    performansın zaman içindeki seyri korunur. Bir videonun 7. gündeki
    retention'ı ile 90. gündeki farklıdır ve ikisi de bilgi.
    """
    with connect() as conn:
        conn.execute(
            "INSERT INTO analytics "
            "(job_id, youtube_video_id, views, avg_view_duration_s, retention_pct, fetched_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (job_id, youtube_video_id, views, avg_view_duration_s, retention_pct, _now()),
        )


def latest_analytics(job_id: int) -> dict[str, Any] | None:
    """İşin en son ölçümü."""
    with connect() as conn:
        row = conn.execute(
            "SELECT * FROM analytics WHERE job_id = ? ORDER BY fetched_at DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        return dict(row) if row else None


def published_with_analytics(channel: str) -> list[dict[str, Any]]:
    """Yayınlanmış işler + en son ölçümleri.

    Eksen performansı bunun üzerinden hesaplanır: `storyboard_json` premise'i
    taşıyor, analytics satırı da o bölümün sonucunu. İkisini birleştirmek
    "hangi mekân daha iyi tuttu" sorusunun tek kaynağı.
    """
    with connect() as conn:
        rows = conn.execute(
            """
            SELECT j.id, j.channel, j.title, j.storyboard_json, j.voice_id,
                   j.published_at, j.youtube_video_id,
                   a.views, a.avg_view_duration_s, a.retention_pct, a.fetched_at
            FROM jobs j
            JOIN analytics a ON a.id = (
                SELECT id FROM analytics WHERE job_id = j.id
                ORDER BY fetched_at DESC LIMIT 1
            )
            WHERE j.channel = ? AND j.status = ?
            ORDER BY j.published_at DESC
            """,
            (channel, JobStatus.PUBLISHED.value),
        ).fetchall()
        return [dict(r) for r in rows]


def published_awaiting_analytics(channel: str | None = None) -> list[dict[str, Any]]:
    """Yayınlanmış ve YouTube kimliği olan işler — ölçüm çekilecek adaylar."""
    sql = (
        "SELECT * FROM jobs WHERE status = ? AND youtube_video_id IS NOT NULL "
        "AND youtube_video_id != ''"
    )
    params: list[Any] = [JobStatus.PUBLISHED.value]
    if channel:
        sql += " AND channel = ?"
        params.append(channel)
    sql += " ORDER BY published_at DESC"
    with connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


# --------------------------------------------------------------------------
# Bakım
# --------------------------------------------------------------------------

def stats() -> dict[str, Any]:
    """doctor ve CLI için özet."""
    with connect() as conn:
        by_status = {
            r["status"]: r["n"]
            for r in conn.execute(
                "SELECT status, COUNT(*) AS n FROM jobs GROUP BY status"
            ).fetchall()
        }
        total_jobs = sum(by_status.values())
    return {
        "db_path": str(config.DB_PATH),
        "total_jobs": total_jobs,
        "by_status": by_status,
        "month_spend_usd": round(month_spend(), 2),
    }


def db_exists() -> bool:
    return Path(config.DB_PATH).exists()
