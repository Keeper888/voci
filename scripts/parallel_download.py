"""Parallel downloader — runs N workers pulling from the pending queue."""
import sys
import logging
import time
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.scraper.db import VociDB
from src.scraper.rss import download_episode

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

DATA_DIR = Path("./data/prod")
WORKERS = 10
BATCH_SIZE = 200


def download_one(ep: dict, data_dir: Path) -> tuple[str, bool]:
    episode_id = ep["episode_id"]
    show_id = ep["show_id"]
    audio_url = ep["audio_url"]
    audio_format = ep.get("audio_format", "mp3")
    output_dir = data_dir / "shows" / show_id / "episodes"
    result = download_episode(audio_url, output_dir, episode_id, audio_format)
    return episode_id, result is not None


def main():
    db = VociDB(DATA_DIR / "index.db")
    total_done = 0

    while True:
        pending = db.get_pending_downloads(limit=BATCH_SIZE)
        if not pending:
            log.info("No more pending downloads")
            break

        log.info(f"Downloading batch of {len(pending)} with {WORKERS} workers...")
        completed = 0
        failed = 0

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            futures = {
                pool.submit(download_one, ep, DATA_DIR): ep
                for ep in pending
            }
            for future in as_completed(futures):
                ep = futures[future]
                episode_id = ep["episode_id"]
                try:
                    _, success = future.result()
                    if success:
                        db.update_episode_state(episode_id, download_state="completed",
                                                file_path=f"shows/{ep['show_id']}/episodes/{episode_id}.mp3",
                                                downloaded_at="datetime('now')")
                        completed += 1
                    else:
                        attempts = ep.get("download_attempts", 0) + 1
                        db.update_episode_state(episode_id,
                                                download_state="failed" if attempts >= 3 else "pending",
                                                download_error="Download failed",
                                                download_attempts=attempts)
                        failed += 1
                except Exception as e:
                    db.update_episode_state(episode_id, download_state="pending",
                                            download_error=str(e))
                    failed += 1

        total_done += completed
        stats = db.get_stats()
        log.info(f"Batch done: {completed} ok, {failed} failed | Total: {stats['download_completed']} eps, {stats['downloaded_hours']:.1f}h")

    db.close()


if __name__ == "__main__":
    main()
