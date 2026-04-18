"""
Diverse downloader — max N episodes per show, maximize speaker variety.
Prioritizes shows with multi-speaker keywords in their description.
"""
import logging
import time
import sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, str(Path(__file__).parent.parent))
from src.scraper.db import VociDB
from src.scraper.rss import download_episode

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger(__name__)

DATA_DIR = Path("./data/prod")
MAX_PER_SHOW_DEFAULT = 2
MAX_PER_SHOW_INTERVIEW = 10  # shows with rotating guests get more
WORKERS = 5
TARGET_HOURS = 1000

# Keywords that signal different guests per episode = more speaker diversity
GUEST_KEYWORDS = [
    "intervista", "ospite", "con ", "insieme a", "feat.",
    "ft.", "special guest", "parliamo con", "incontro con",
    "dialogo con", "conversazione con", "chiacchierata con",
]

# Keywords that signal monologue = skip entirely
MONOLOGUE_KEYWORDS = [
    "meditazione", "asmr", "audiolibro", "lettura",
    "narrazione", "monologo", "racconto letto",
]


def _is_monologue_show(name: str, description: str) -> bool:
    """Detect shows that are likely monologues."""
    text = f"{name} {description}".lower()
    return any(kw in text for kw in MONOLOGUE_KEYWORDS)


def _is_interview_show(name: str, description: str) -> bool:
    """Detect shows with rotating guests (different speakers each episode)."""
    text = f"{name} {description}".lower()
    return any(kw in text for kw in GUEST_KEYWORDS)


def _episode_has_guest(title: str) -> bool:
    """Check if episode title suggests a guest speaker."""
    title_lower = (title or "").lower()
    return any(kw in title_lower for kw in GUEST_KEYWORDS)


def get_diverse_queue(db: VociDB, max_per_show: int, target_hours: float) -> list[dict]:
    """Build a download queue maximizing speaker diversity.

    Strategy:
    - Skip monologue shows entirely
    - Interview shows with rotating guests: up to MAX_PER_SHOW_INTERVIEW episodes,
      but only episodes whose title suggests a different guest
    - Other shows: max MAX_PER_SHOW_DEFAULT episodes
    """
    conn = db.conn

    shows = conn.execute("""
        SELECT s.show_id, s.name, s.multi_speaker_score, s.description,
               COUNT(e.episode_id) as pending_eps
        FROM shows s
        JOIN episodes e ON e.show_id = s.show_id
        WHERE e.download_state = 'pending' AND e.duration_seconds IS NOT NULL
          AND e.duration_seconds BETWEEN 600 AND 7200
        GROUP BY s.show_id
        ORDER BY s.multi_speaker_score DESC, pending_eps DESC
    """).fetchall()

    queue = []
    total_hours = 0
    shows_added = 0
    shows_skipped_mono = 0

    for show in shows:
        if total_hours >= target_hours:
            break

        show_id = show["show_id"]
        name = show["name"] or ""
        desc = show["description"] or ""

        # Skip monologue shows
        if _is_monologue_show(name, desc):
            shows_skipped_mono += 1
            continue

        # Determine max episodes for this show
        is_interview = _is_interview_show(name, desc)
        show_max = MAX_PER_SHOW_INTERVIEW if is_interview else MAX_PER_SHOW_DEFAULT

        # Check how many we already downloaded from this show
        already = conn.execute(
            "SELECT COUNT(*) as c FROM episodes WHERE show_id = ? AND download_state = 'completed'",
            (show_id,)
        ).fetchone()["c"]

        remaining_slots = max(0, show_max - already)
        if remaining_slots == 0:
            continue

        # Get pending episodes
        episodes = conn.execute("""
            SELECT episode_id, show_id, audio_url, audio_format, duration_seconds, title
            FROM episodes
            WHERE show_id = ? AND download_state = 'pending'
              AND duration_seconds BETWEEN 600 AND 7200
            ORDER BY duration_seconds DESC
        """, (show_id,)).fetchall()

        added_from_show = 0
        for ep in episodes:
            if added_from_show >= remaining_slots:
                break

            # For interview shows, prefer episodes with guest indicators in title
            if is_interview and added_from_show >= MAX_PER_SHOW_DEFAULT:
                if not _episode_has_guest(ep["title"]):
                    continue

            queue.append(dict(ep))
            total_hours += (ep["duration_seconds"] or 0) / 3600
            added_from_show += 1

        if added_from_show > 0:
            shows_added += 1

    log.info(f"Queue: {len(queue)} episodes from {shows_added} shows, ~{total_hours:.0f}h")
    log.info(f"Skipped {shows_skipped_mono} monologue shows")
    if shows_added > 0:
        log.info(f"Avg eps/show: {len(queue)/shows_added:.1f}")
    return queue


def main():
    db = VociDB(DATA_DIR / "index.db")

    queue = get_diverse_queue(db, MAX_PER_SHOW_DEFAULT, TARGET_HOURS)
    if not queue:
        log.info("No episodes to download")
        return

    total_done = 0
    total_failed = 0
    batch_size = 50

    for batch_start in range(0, len(queue), batch_size):
        batch = queue[batch_start:batch_start + batch_size]
        log.info(f"Batch {batch_start//batch_size + 1}: {len(batch)} episodes")

        with ThreadPoolExecutor(max_workers=WORKERS) as pool:
            def dl(ep):
                eid = ep["episode_id"]
                sid = ep["show_id"]
                url = ep["audio_url"]
                fmt = ep.get("audio_format", "mp3")
                r = download_episode(url, DATA_DIR / "shows" / sid / "episodes", eid, fmt)
                return eid, r is not None

            futures = {pool.submit(dl, ep): ep for ep in batch}
            for f in as_completed(futures):
                ep = futures[f]
                eid = ep["episode_id"]
                try:
                    _, ok = f.result()
                    if ok:
                        db.update_episode_state(eid, download_state="completed",
                                                file_path=f"shows/{ep['show_id']}/episodes/{eid}.mp3")
                        total_done += 1
                    else:
                        db.update_episode_state(eid, download_state="failed",
                                                download_error="Download failed")
                        total_failed += 1
                except Exception:
                    db.update_episode_state(eid, download_state="pending")
                    total_failed += 1

        stats = db.get_stats()
        log.info(f"Progress: {total_done} ok, {total_failed} failed | "
                 f"Total downloaded: {stats['download_completed']} eps, {stats['downloaded_hours']:.0f}h")
        time.sleep(1)

    db.close()
    log.info(f"Done. {total_done} downloaded, {total_failed} failed")


if __name__ == "__main__":
    main()
