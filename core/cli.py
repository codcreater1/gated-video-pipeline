"""Komut satırı arayüzü.

    otomasyon doctor            # ortam denetimi
    otomasyon init              # veritabanı ve dizinleri kur
    otomasyon status            # kuyruk ve bütçe durumu
    otomasyon queue             # onay bekleyenleri listele
    otomasyon review <id>       # inceleme kartını göster
    otomasyon approve <id>      # onayla
    otomasyon reject <id> "..." # reddet (iş silinmez, kuyruğa döner)
"""

from __future__ import annotations

import json

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from core import approval, budget, config, db

app = typer.Typer(help="Çocuk videoları otomatik üretim hattı", no_args_is_help=True)
console = Console()


@app.command()
def doctor() -> None:
    """Ortamı ve yapılandırmayı denetler."""
    from core import doctor as doc

    raise typer.Exit(doc.run())


@app.command()
def init() -> None:
    """Veri dizinlerini ve veritabanını oluşturur. Idempotent."""
    config.ensure_dirs()
    db.init()
    console.print(f"[green]Hazır.[/green] Veri kökü: {config.DATA_ROOT}")


@app.command("setup-node")
def setup_node(
    force: bool = typer.Option(False, help="Mevcut kurulumun üstüne yaz"),
) -> None:
    """n8n için taşınabilir Node 22'yi indirir (sistem PATH'ine dokunmaz).

    nvm-windows kullanılmıyor: sistemde normal kurulu bir Node 25 varken nvm
    `node` komutunu devralır ve Remotion tarafını karıştırır.
    """
    import io
    import json as _json
    import os
    import urllib.request
    import zipfile
    from pathlib import Path

    # C:'de — harici diskte değil. n8n'in 232k dosyalık ağacı exFAT'te kurulmuyor.
    tools = Path(os.environ["LOCALAPPDATA"]) / "otomasyon-tools"
    node_home = tools / "node22"
    if node_home.exists() and not force:
        console.print(f"[yellow]Zaten kurulu:[/yellow] {node_home}  (--force ile yenile)")
        return

    console.print("Node 22 LTS sürümü aranıyor…")
    with urllib.request.urlopen("https://nodejs.org/dist/index.json", timeout=30) as r:
        index = _json.loads(r.read())
    release = next(v for v in index if v["version"].startswith("v22."))
    version = release["version"]
    url = f"https://nodejs.org/dist/{version}/node-{version}-win-x64.zip"
    console.print(f"  {version} (LTS {release['lts']}) indiriliyor…")

    with urllib.request.urlopen(url, timeout=600) as r:
        blob = r.read()
    console.print(f"  {len(blob) // (1024 * 1024)} MB indirildi, açılıyor…")

    tools.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        z.extractall(tools)

    extracted = tools / f"node-{version}-win-x64"
    if node_home.exists():
        import shutil as _shutil

        _shutil.rmtree(node_home)
    extracted.rename(node_home)

    console.print(f"[green]Hazır:[/green] {node_home}")
    console.print("[dim]Sonraki adım: .\\scripts\\n8n.ps1 -Install[/dim]")


@app.command()
def status() -> None:
    """Kuyruk durumu, bütçe ve kadans."""
    s = db.stats()
    b = budget.summary()
    cadence = config.active_cadence()
    aktif = config.active_channels()

    table = Table(title="İş kuyruğu", show_header=True)
    table.add_column("Durum")
    table.add_column("Adet", justify="right")
    for st, n in sorted(s["by_status"].items()):
        table.add_row(st, str(n))
    if not s["by_status"]:
        table.add_row("(boş)", "0")
    console.print(table)

    console.print(
        Panel(
            f"Bu ay: [bold]${b['month_spent_usd']:.2f}[/bold] / ${b['month_cap_usd']:.2f}"
            f"   (kalan ${b['month_remaining_usd']:.2f})\n"
            f"Video başı tavan: ${b['per_video_cap_usd']:.2f}",
            title="Bütçe",
        )
    )

    console.print(
        Panel(
            f"Faz: [bold]{cadence.phase}[/bold]\n"
            f"Kanal başına haftalık bölüm: {cadence.episodes_per_week_per_channel}\n"
            f"Günlük shorts: {cadence.shorts_per_day}\n"
            f"Mutlak günlük tavan: {config.HARD_DAILY_CAP_LONGFORM} uzun-form / "
            f"{config.HARD_DAILY_CAP_SHORTS} shorts\n"
            f"Aktif kanal: {', '.join(p.display_name for p in aktif.values())}",
            title="Kadans",
        )
    )

    if not config.REQUIRE_HUMAN_APPROVAL:
        console.print("[bold red]UYARI: onay kapısı KAPALI.[/bold red]")


@app.command()
def queue() -> None:
    """Onay bekleyen videoları listeler."""
    cards = approval.pending()
    if not cards:
        console.print("Onay bekleyen video yok.")
        return

    table = Table(title=f"Onay bekleyen ({len(cards)})")
    table.add_column("ID", justify="right")
    table.add_column("Başlık")
    table.add_column("Süre")
    table.add_column("Maliyet", justify="right")
    for c in cards:
        table.add_row(
            str(c.get("job_id")),
            c.get("title", "?"),
            c.get("duration_human", "?"),
            f"${c.get('cost_usd', 0):.2f}",
        )
    console.print(table)
    console.print("\n[dim]İncelemek için: otomasyon review <id>[/dim]")


@app.command()
def review(job_id: int) -> None:
    """İnceleme kartını ve değer testi sorularını gösterir."""
    path = config.PENDING_DIR / f"job_{job_id}.json"
    if not path.exists():
        console.print(f"[red]İnceleme kartı bulunamadı: {path}[/red]")
        raise typer.Exit(1)

    c = json.loads(path.read_text(encoding="utf-8"))

    console.print(
        Panel(
            f"[bold]{c['title']}[/bold]\n\n"
            f"Kanal: {c['channel']}  |  Format: {c['format']}  |  "
            f"Süre: {c['duration_human']}  |  Maliyet: ${c['cost_usd']:.2f}\n"
            f"Made for Kids: {'EVET' if c['made_for_kids'] else 'hayır'}  |  "
            f"Sahne: {c['scene_count']}\n"
            f"Konu: {c['topic']}\n\n"
            f"Dosya: {c['video_path']}",
            title=f"İş #{job_id}",
        )
    )

    console.print(Panel(c["script_excerpt"], title="Senaryo (başlangıç)"))

    if c.get("variation_notes"):
        console.print(Panel("\n".join(c["variation_notes"]), title="Varyasyon kapısı notları"))

    console.print("\n[bold]Değer testi[/bold] — biri bile 'hayır' ise reddet:\n")
    for i, q in enumerate(c["checklist"], 1):
        console.print(f"  {i}. {q}")

    console.print(
        f"\n[dim]Videoyu izle, sonra:\n"
        f"  otomasyon approve {job_id}\n"
        f'  otomasyon reject {job_id} "gerekçe"[/dim]'
    )


@app.command()
def approve(job_id: int, reviewer: str = typer.Option("human", help="Onaylayan")) -> None:
    """Videoyu onaylar ve yükleme kuyruğuna alır."""
    try:
        approval.approve(job_id, reviewer=reviewer)
    except (ValueError, approval.ApprovalRequired) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc
    console.print(f"[green]İş #{job_id} onaylandı.[/green]")


@app.command()
def reject(job_id: int, reason: str) -> None:
    """Videoyu reddeder. İş silinmez, yeniden üretim kuyruğuna döner."""
    approval.reject(job_id, reason)
    console.print(f"[yellow]İş #{job_id} reddedildi:[/yellow] {reason}")


if __name__ == "__main__":
    app()
