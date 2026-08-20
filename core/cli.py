"""Komut satırı arayüzü.

    otomasyon doctor            # ortam denetimi
    otomasyon init              # veritabanı ve dizinleri kur
    otomasyon status            # kuyruk ve bütçe durumu
    otomasyon queue             # onay bekleyenleri listele
    otomasyon review <id>       # inceleme kartını göster
    otomasyon approve <id>      # onayla
    otomasyon reject <id> "..." # reddet (iş silinmez, kuyruğa döner)
    otomasyon authorize <kanal> # YouTube OAuth (kanal başına bir kez)
    otomasyon uploads           # yükleme bekleyen onaylı işler
    otomasyon publish <id>      # YouTube'a yükle
    otomasyon analytics         # yayın sonrası performans ve eksen ağırlıkları
    otomasyon short <id>        # yayınlanmış bölümden dikey Short türet
    otomasyon compile           # yayınlanmış bölümlerden 40-60 dk derleme
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


@app.command()
def authorize(channel: str) -> None:
    """Kanalı YouTube'a yetkilendirir. Kanal başına bir kez, tarayıcı açılır."""
    from core import publish

    try:
        ch = config.Channel(channel)
    except ValueError as exc:
        valid = ", ".join(c.value for c in config.Channel)
        console.print(f"[red]Bilinmeyen kanal: {channel}[/red] (geçerli: {valid})")
        raise typer.Exit(1) from exc

    console.print(
        f"Tarayıcı açılıyor — [bold]{ch.value}[/bold] kanalının "
        f"Google hesabıyla giriş yap."
    )
    try:
        path = publish.authorize(ch)
    except publish.NotAuthorized as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    console.print(f"[green]Yetkilendirildi.[/green] Token: {path}")


@app.command()
def uploads() -> None:
    """Onaylanmış ama henüz YouTube'a yüklenmemiş işler."""
    from core import publish

    jobs = publish.pending_uploads()
    if not jobs:
        console.print("Yükleme bekleyen iş yok.")
        return

    table = Table(title=f"Yükleme bekleyen ({len(jobs)})")
    table.add_column("ID", justify="right")
    table.add_column("Kanal")
    table.add_column("Başlık")
    for j in jobs:
        table.add_row(str(j["id"]), j["channel"], j["title"] or "?")
    console.print(table)
    console.print("\n[dim]Yüklemek için: otomasyon publish <id>[/dim]")


@app.command()
def publish(
    job_id: int,
    privacy: str = typer.Option("public", help="public | unlisted | private"),
) -> None:
    """Onaylanmış videoyu YouTube'a yükler.

    Geri alınamaz tek işlem bu. Onay kapısı, günlük tavan ve Made for Kids
    bayrağı yükleme öncesi bir kez daha denetlenir.
    """
    from core import publish as pub

    try:
        result = pub.publish(job_id, privacy_status=privacy)
    except (pub.PublishError, approval.ApprovalRequired, ValueError) as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    console.print(
        Panel(
            f"[bold]{result.title}[/bold]\n\n"
            f"{result.url}\n"
            f"Kanal: {result.channel}  |  Gizlilik: {result.privacy_status}  |  "
            f"Made for Kids: {'EVET' if result.made_for_kids else 'hayır'}",
            title=f"Yayınlandı — İş #{job_id}",
        )
    )


@app.command()
def short(
    parent_job_id: int,
    scene: int = typer.Option(0, help="Kaynak bölümün hangi sahnesi"),
) -> None:
    """Yayınlanmış bir bölümden dikey Short türetir ve onay kuyruğuna alır.

    Yeni senaryo yazılmaz, yeni fikir üretilmez: LLM maliyeti $0. Made for Kids
    bir kanalda Shorts, kalan tek native gelir yolu (docs/content-guidelines.md §1).
    """
    from core import shorts

    try:
        job_id, plan = shorts.create(parent_job_id, scene_index=scene)
    except shorts.ShortError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    card = approval.submit(
        job_id, variation_notes=[f"#{parent_job_id} bölümünden türetildi"]
    )
    excerpt = plan.narration_text[:160]
    if len(plan.narration_text) > 160:
        excerpt += "…"

    console.print(
        Panel(
            f"[bold]{card.title}[/bold]\n\n"
            f"Kaynak: bölüm #{plan.parent_job_id}, sahne {plan.scene_index}\n"
            f"Anlatım: {excerpt}",
            title=f"Short hazır — İş #{job_id}",
        )
    )
    console.print(f"\n[dim]İncelemek için: otomasyon review {job_id}[/dim]")


@app.command("compile")
def compile_cmd(
    channel: str = typer.Option("bedtime", help="Kanal"),
    target: int = typer.Option(0, help="Hedef süre (saniye); 0 = format hedefi"),
) -> None:
    """Yayınlanmış bölümleri 40-60 dakikalık tek videoda birleştirir.

    Render EDİLMEZ, ffmpeg ile stream-copy birleştirilir — 60 dakikalık tek
    parça render bu makinede ~2.3 saat sürerdi (docs/benchmarks.md).
    """
    from core import compilation

    try:
        ch = config.Channel(channel)
    except ValueError as exc:
        console.print(f"[red]Bilinmeyen kanal: {channel}[/red]")
        raise typer.Exit(1) from exc

    try:
        with console.status("Bölümler birleştiriliyor…"):
            job_id, plan = compilation.build(ch, target_seconds=target or None)
    except compilation.CompilationError as exc:
        console.print(f"[red]{exc}[/red]")
        raise typer.Exit(1) from exc

    table = Table(title=f"Derleme #{job_id} — {plan.total_seconds // 60} dakika")
    table.add_column("Sıra", justify="right")
    table.add_column("Bölüm", justify="right")
    table.add_column("Başlık")
    for i, m in enumerate(plan.members, 1):
        table.add_row(str(i), f"#{m['id']}", m["title"] or "?")
    console.print(table)

    approval.submit(job_id, variation_notes=[f"{len(plan.members)} bölümden derlendi"])
    console.print(f"\n[dim]İncelemek için: otomasyon review {job_id}[/dim]")


@app.command()
def analytics(
    refresh: bool = typer.Option(False, help="Önce YouTube'dan ölçümleri çek"),
    channel: str = typer.Option("bedtime", help="Kanal"),
) -> None:
    """Yayın sonrası performans ve ideation'a giden eksen ağırlıkları.

    Ağırlıklar sınırlıdır: en iyi eksen değeri nötre göre en fazla iki kat
    olası. Sınırsız optimizasyon varyasyon kapısını tetikler.
    """
    from core import analytics as an

    try:
        ch = config.Channel(channel)
    except ValueError as exc:
        console.print(f"[red]Bilinmeyen kanal: {channel}[/red]")
        raise typer.Exit(1) from exc

    if refresh:
        with console.status("YouTube'dan ölçümler çekiliyor…"):
            stats = an.refresh(ch)
        console.print(f"[green]{len(stats)} video ölçüldü.[/green]\n")

    s = an.summary(ch)
    if not s["measured"]:
        console.print(
            "Ölçülmüş video yok. Yayından sonra en az "
            f"{config.ANALYTICS_MIN_VIDEO_AGE_DAYS} gün geçmeli, sonra: "
            "[dim]otomasyon analytics --refresh[/dim]"
        )
        return

    console.print(
        Panel(
            f"Ölçülen video: [bold]{s['measured']}[/bold]\n"
            f"Toplam izlenme: {s['total_views']:,}\n"
            f"Ortalama tutma: [bold]%{s['mean_retention']:.1f}[/bold]",
            title="Kanal performansı",
        )
    )

    for axis, scores in s["axes"].items():
        if not scores:
            continue
        table = Table(title=f"{axis} — ideation ağırlıkları")
        table.add_column("Değer")
        table.add_column("Bölüm", justify="right")
        table.add_column("Tutma", justify="right")
        table.add_column("Ağırlık", justify="right")
        for sc in scores[:8]:
            table.add_row(
                sc.value,
                str(sc.samples),
                f"%{sc.mean_retention:.1f}",
                f"×{sc.weight:.2f}" if sc.confident else "[dim]×1.00 (az veri)[/dim]",
            )
        console.print(table)


if __name__ == "__main__":
    app()
