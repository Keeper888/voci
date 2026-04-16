# Podcast Scraper

## Goal

Collect 5,000+ hours of Italian multi-speaker conversational podcast audio from public sources.

## Sources

### Primary: Apple Podcasts / iTunes API

Apple's podcast directory is the largest and provides RSS feed URLs directly.

- Search endpoint: `https://itunes.apple.com/search?term=*&country=IT&media=podcast&lang=it_it`
- Paginate through Italian podcast listings
- Extract RSS feed URLs from results
- Parse RSS for episode MP3/M4A download links

### Secondary: Spotify Podcast Catalog

Spotify doesn't expose direct audio URLs, but their catalog API provides metadata useful for discovery. Actual audio must come from the RSS feed.

### Tertiary: Podchaser / Podcast Index

Open podcast directories with API access. Good for discovering shows not indexed elsewhere.

## Podcast Selection Criteria

Not all podcasts are useful. We need **multi-speaker conversation**, not monologues or music.

### Include
- Interview shows (2+ speakers)
- Panel discussions, roundtables
- Casual conversation / chat shows
- Debate formats
- Comedy podcasts with banter
- Sports commentary with multiple hosts

### Exclude
- Solo narration / storytelling (single speaker, rehearsed)
- Music podcasts (high music-to-speech ratio)
- News bulletins (scripted, formal register)
- Audiobook-style readings
- ASMR / meditation
- Shows primarily in other languages

### Detection Heuristics

Automatically classify podcasts before downloading all episodes:

1. **Episode description keywords**: "intervista", "ospite", "parliamo con", "dibattito", "tavola rotonda" → likely multi-speaker
2. **Episode duration**: 30-120 min is the sweet spot for conversation
3. **Sample-based validation**: Download 1-2 episodes per show, run quick diarization — if <2 speakers detected, skip the show
4. **Metadata signals**: Multiple host names in show description, "con" in episode titles

## Download Strategy

### Rate Limiting
- Max 5 concurrent downloads per source domain
- 1-second delay between requests to same host
- Respect robots.txt and rate limit headers
- Rotate user agents

### Storage Layout
```
data/raw/
├── index.db                    # SQLite: all shows, episodes, state
├── shows/
│   ├── {show_id}/
│   │   ├── metadata.json       # Show-level metadata
│   │   ├── episodes/
│   │   │   ├── {ep_id}.mp3     # Raw audio
│   │   │   ├── {ep_id}.json    # Episode metadata (title, date, duration, speakers)
│   │   │   └── ...
│   │   └── ...
│   └── ...
└── failed/                     # Failed downloads for retry
```

### Deduplication
- Hash-based (audio fingerprint) to catch same episode across different feeds
- Title + duration matching as a fast pre-filter

## Metadata Schema

```json
{
  "show_id": "sha256_of_feed_url",
  "show_name": "Name of the show",
  "feed_url": "https://...",
  "language": "it",
  "categories": ["Society & Culture", "Comedy"],
  "host_count_estimate": 2,
  "episode_count": 150,
  "total_duration_hours": 200.5,
  "episodes": [
    {
      "episode_id": "sha256_of_audio_url",
      "title": "Episode title",
      "published": "2025-06-15",
      "duration_seconds": 3600,
      "audio_url": "https://...",
      "audio_format": "mp3",
      "file_size_mb": 85.2,
      "download_state": "completed",
      "processing_state": "pending"
    }
  ]
}
```

## Estimated Yield

| Source Type | Shows | Avg Episodes | Avg Duration | Total Hours |
|------------|-------|-------------|-------------|-------------|
| Top Italian interview pods | ~200 | 150 | 60 min | ~3,000h |
| Regional/niche conversation | ~500 | 50 | 45 min | ~1,875h |
| Comedy/banter shows | ~100 | 80 | 50 min | ~667h |
| **Total estimated** | **~800** | | | **~5,500h** |

After filtering for quality and multi-speaker content, target yield is **5,000h usable**.

## Legal Considerations

- All podcasts are publicly distributed via RSS (designed for download)
- Audio is used for research purposes (dataset creation)
- No redistribution of raw audio — only derived transcripts
- Show attribution maintained in metadata
- Respect any explicit licensing in feed metadata
