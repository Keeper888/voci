import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from .db import VociDB
from . import spreaker, podcast_index, apple, rss

console = Console()


def setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


@click.group()
@click.option("--data-dir", default="./data/raw", help="Base data directory")
@click.option("-v", "--verbose", is_flag=True)
@click.pass_context
def cli(ctx, data_dir, verbose):
    """Voci — Italian conversational speech dataset pipeline."""
    setup_logging(verbose)
    ctx.ensure_object(dict)
    data_path = Path(data_dir)
    data_path.mkdir(parents=True, exist_ok=True)
    ctx.obj["data_dir"] = data_path
    ctx.obj["db"] = VociDB(data_path / "index.db")


@cli.command()
@click.option("--spreaker/--no-spreaker", "use_spreaker", default=True, help="Scrape Spreaker")
@click.option("--apple/--no-apple", "use_apple", default=True, help="Scrape Apple Charts")
@click.option("--podcast-index/--no-podcast-index", "use_pi", default=False,
              help="Scrape Podcast Index (requires API key)")
@click.option("--pi-key", envvar="PODCAST_INDEX_KEY", help="Podcast Index API key")
@click.option("--pi-secret", envvar="PODCAST_INDEX_SECRET", help="Podcast Index API secret")
@click.pass_context
def discover(ctx, use_spreaker, use_apple, use_pi, pi_key, pi_secret):
    """Discover Italian podcasts from all sources."""
    db = ctx.obj["db"]
    total = 0

    if use_spreaker:
        console.print("\n[bold cyan]--- Spreaker Discovery ---[/bold cyan]")
        n = spreaker.discover_by_search(db)
        console.print(f"  Search: [green]{n}[/green] new shows")
        total += n

        n = spreaker.discover_by_category(db)
        console.print(f"  Categories: [green]{n}[/green] new shows")
        total += n

    if use_apple:
        console.print("\n[bold cyan]--- Apple Charts Discovery ---[/bold cyan]")
        n = apple.discover_all(db)
        console.print(f"  Charts: [green]{n}[/green] new shows")
        total += n

    if use_pi:
        if not pi_key or not pi_secret:
            console.print("[red]Podcast Index requires --pi-key and --pi-secret (or env vars)[/red]")
            sys.exit(1)
        console.print("\n[bold cyan]--- Podcast Index Discovery ---[/bold cyan]")
        n = podcast_index.discover_all(db, pi_key, pi_secret)
        console.print(f"  Podcast Index: [green]{n}[/green] new shows")
        total += n

    console.print(f"\n[bold green]Total new shows discovered: {total}[/bold green]")


@cli.command()
@click.pass_context
def episodes(ctx):
    """Fetch episode lists for all discovered shows."""
    db = ctx.obj["db"]

    console.print("\n[bold cyan]--- Fetching Episodes ---[/bold cyan]")

    # Spreaker shows: use API
    console.print("Fetching from Spreaker API...")
    n = spreaker.fetch_all_episodes(db)
    console.print(f"  Spreaker episodes: [green]{n}[/green]")

    # Other sources: use RSS
    console.print("Parsing RSS feeds...")
    n = rss.fetch_all_rss(db)
    console.print(f"  RSS episodes: [green]{n}[/green]")


@cli.command()
@click.option("--batch-size", default=100, help="Number of episodes per batch")
@click.option("--continuous", is_flag=True, help="Keep downloading until all done")
@click.pass_context
def download(ctx, batch_size, continuous):
    """Download audio for pending episodes."""
    db = ctx.obj["db"]
    data_dir = ctx.obj["data_dir"]

    console.print("\n[bold cyan]--- Downloading Audio ---[/bold cyan]")

    total = 0
    while True:
        n = rss.download_batch(db, data_dir, batch_size=batch_size)
        total += n
        if not continuous or n == 0:
            break
        console.print(f"  Batch done: {n} downloaded (total: {total})")

    console.print(f"\n[bold green]Downloaded: {total} episodes[/bold green]")


@cli.command()
@click.pass_context
def status(ctx):
    """Show current scraping stats."""
    db = ctx.obj["db"]
    stats = db.get_stats()

    table = Table(title="Voci Scraper Status")
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green", justify="right")

    table.add_row("Total shows", str(stats["total_shows"]))
    table.add_row("Total episodes", str(stats["total_episodes"]))
    table.add_row("Total hours (known)", f"{stats['total_hours']:.1f}h")
    table.add_row("", "")
    table.add_row("Downloads pending", str(stats["download_pending"]))
    table.add_row("Downloads in progress", str(stats["download_downloading"]))
    table.add_row("Downloads completed", str(stats["download_completed"]))
    table.add_row("Downloads failed", str(stats["download_failed"]))
    table.add_row("", "")
    table.add_row("Downloaded hours", f"{stats['downloaded_hours']:.1f}h")
    table.add_row("Target", "5,000h")
    pct = (stats["downloaded_hours"] / 5000) * 100 if stats["downloaded_hours"] else 0
    table.add_row("Progress", f"{pct:.1f}%")

    console.print(table)


@cli.command()
@click.pass_context
def sources(ctx):
    """Show breakdown by source."""
    db = ctx.obj["db"]

    rows = db.conn.execute(
        "SELECT source, COUNT(*) as shows, "
        "COALESCE(SUM(episode_count), 0) as eps "
        "FROM shows GROUP BY source"
    ).fetchall()

    table = Table(title="Shows by Source")
    table.add_column("Source", style="cyan")
    table.add_column("Shows", style="green", justify="right")
    table.add_column("Episodes (est)", style="yellow", justify="right")

    for row in rows:
        table.add_row(row["source"], str(row["shows"]), str(row["eps"]))

    console.print(table)


def main():
    cli()


if __name__ == "__main__":
    main()
