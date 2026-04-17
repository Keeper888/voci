import hashlib
import logging
import time
from pathlib import Path

import feedparser
import requests

from .db import VociDB

log = logging.getLogger(__name__)

RATE_LIMIT_DELAY = 0.5


def _make_episode_id(audio_url: str) -> str:
    return hashlib.sha256(audio_url.encode()).hexdigest()[:16]


def _parse_duration(duration_str: str) -> int | None:
    """Parse iTunes duration format (HH:MM:SS or seconds) to seconds."""
    if not duration_str:
        return None
    try:
        # Plain seconds
        if duration_str.isdigit():
            return int(duration_str)
        # HH:MM:SS or MM:SS
        parts = duration_str.split(":")
        if len(parts) == 3:
            return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
        elif len(parts) == 2:
            return int(parts[0]) * 60 + int(parts[1])
    except (ValueError, IndexError):
        pass
    return None


def fetch_episodes_from_rss(db: VociDB, show_id: str, feed_url: str) -> int:
    """Parse an RSS feed and store all episodes."""
    try:
        feed = feedparser.parse(feed_url)
    except Exception as e:
        log.warning(f"Failed to parse RSS: {feed_url} — {e}")
        return 0

    if feed.bozo and not feed.entries:
        log.warning(f"Malformed RSS with no entries: {feed_url}")
        return 0

    new_count = 0
    for entry in feed.entries:
        # Find audio enclosure
        audio_url = None
        for enc in getattr(entry, "enclosures", []):
            if enc.get("type", "").startswith("audio/") or enc.get("href", "").endswith((".mp3", ".m4a", ".wav")):
                audio_url = enc.get("href")
                break

        if not audio_url:
            # Try media content
            for media in getattr(entry, "media_content", []):
                if media.get("type", "").startswith("audio/"):
                    audio_url = media.get("url")
                    break

        if not audio_url:
            continue

        episode_id = _make_episode_id(audio_url)
        duration_str = entry.get("itunes_duration") or entry.get("duration")
        duration_s = _parse_duration(str(duration_str)) if duration_str else None

        # Determine format from URL
        audio_format = "mp3"
        if ".m4a" in audio_url:
            audio_format = "m4a"
        elif ".wav" in audio_url:
            audio_format = "wav"

        is_new = db.upsert_episode(
            episode_id=episode_id,
            show_id=show_id,
            audio_url=audio_url,
            title=entry.get("title"),
            published_at=entry.get("published"),
            duration_seconds=duration_s,
            audio_format=audio_format,
        )

        if is_new:
            new_count += 1

    return new_count


def fetch_all_rss(db: VociDB) -> int:
    """Fetch episodes from RSS feeds for all shows that have feed_url but aren't from Spreaker
    (Spreaker uses its own API for episode listing)."""
    shows = db.conn.execute(
        "SELECT show_id, feed_url FROM shows "
        "WHERE feed_url IS NOT NULL AND state = 'discovered' AND source != 'spreaker'"
    ).fetchall()

    total = 0
    for i, show in enumerate(shows):
        log.info(f"Parsing RSS [{i+1}/{len(shows)}]: {show['feed_url']}")
        new = fetch_episodes_from_rss(db, show["show_id"], show["feed_url"])
        total += new
        db.update_show_state(show["show_id"], "validated")
        log.info(f"  → {new} episodes")
        time.sleep(RATE_LIMIT_DELAY)

    return total


def download_episode(audio_url: str, output_dir: Path, episode_id: str,
                     audio_format: str = "mp3") -> Path | None:
    """Download a single episode audio file."""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{episode_id}.{audio_format}"

    if output_path.exists():
        return output_path

    try:
        resp = requests.get(audio_url, stream=True, timeout=120, allow_redirects=True,
                            headers={"User-Agent": "VociCollector/1.0"})
        resp.raise_for_status()

        with open(output_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)

        return output_path
    except requests.RequestException as e:
        log.warning(f"Download failed: {audio_url} — {e}")
        if output_path.exists():
            output_path.unlink()
        return None


def download_batch(db: VociDB, output_base: Path, batch_size: int = 100,
                   max_concurrent: int = 5) -> int:
    """Download a batch of pending episodes."""
    pending = db.get_pending_downloads(limit=batch_size)
    if not pending:
        log.info("No pending downloads")
        return 0

    completed = 0
    for i, ep in enumerate(pending):
        episode_id = ep["episode_id"]
        show_id = ep["show_id"]
        audio_url = ep["audio_url"]
        audio_format = ep.get("audio_format", "mp3")

        log.info(f"Downloading [{i+1}/{len(pending)}]: {ep.get('title', episode_id)}")
        db.update_episode_state(episode_id, download_state="downloading",
                                download_attempts=ep.get("download_attempts", 0) + 1)

        output_dir = output_base / "shows" / show_id / "episodes"
        result = download_episode(audio_url, output_dir, episode_id, audio_format)

        if result:
            db.update_episode_state(
                episode_id,
                download_state="completed",
                file_path=str(result),
                downloaded_at="datetime('now')",
            )
            completed += 1
        else:
            db.update_episode_state(
                episode_id,
                download_state="failed" if ep.get("download_attempts", 0) >= 3 else "pending",
                download_error="Download failed",
            )

        time.sleep(0.5)

    log.info(f"Downloaded {completed}/{len(pending)} episodes")
    return completed
