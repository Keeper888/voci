# Podcast Scraper

## Goal

Collect 6,500+ hours of Italian multi-speaker conversational podcast audio from public sources (filters will reduce to ~5,000h usable).

## Approach: API Reverse Engineering

**No browser automation.** We reverse-engineer the HTTP APIs that podcast platforms use internally. Direct requests only — faster, more reliable, harder to detect.

**ProtonVPN** for IP rotation and privacy.

## Sources (Priority Order)

### 1. Spreaker (Primary — Best Source for Italian)

Spreaker is the dominant podcast platform in Italy. Their API is fully open, no auth required, and provides **direct MP3 download URLs**.

**Base URL:** `https://api.spreaker.com/v2`

**Search shows:**
```bash
curl -s "https://api.spreaker.com/v2/search?type=shows&q=italia&limit=50"
```
Pagination: `next_url` in response provides cursor-based pagination with `offset` param.

**Browse by category:**
```bash
# Category IDs: 92=Arts, 99=Business, 106=Comedy, 110=Education, 115=Fiction,
# 120=History, 121=Health, 128=Kids, 133=Leisure, 142=Music, 146=News,
# 154=Religion, 162=Science, 172=Society, 178=Sports, 194=Technology,
# 195=True Crime, 196=TV
curl -s "https://api.spreaker.com/v2/explore/categories/146/items?limit=50"
```
Pagination: `next_url` with `last_id` param.

**Show detail (includes language):**
```bash
curl -s "https://api.spreaker.com/v2/shows/{show_id}"
```
Returns: `language` ("it"), `title`, `description`, `category`, `itunes_url`, `author_name`

**List all episodes (includes direct download URLs):**
```bash
curl -s "https://api.spreaker.com/v2/shows/{show_id}/episodes?limit=50"
```
Returns per episode: `title`, `duration` (ms), `published_at`, `download_url`, `playback_url`, `download_enabled`

**Direct episode download:**
```bash
curl -L "https://api.spreaker.com/v2/episodes/{episode_id}/download.mp3" -o episode.mp3
# Returns 302 redirect to CloudFront CDN with signed URL
```

**RSS feed (alternative):**
```bash
curl -s "https://www.spreaker.com/show/{show_id}/episodes/feed"
```

**Strategy:** Search Italian keywords (notizie, storia, cronaca, politica, sport, calcio, tecnologia, scienza, cultura, intervista, dibattito, etc.) + browse all 19 categories. Filter by `language=="it"`. Use API episode listing for complete episode history (better than RSS which may truncate).

### 2. Podcast Index (Best for Bulk Discovery)

Open podcast directory with `lang=it` filter and RSS URLs in responses.

**Base URL:** `https://api.podcastindex.org/api/1.0`
**Auth:** Free API key required — register at https://api.podcastindex.org

**Required headers:**
```
User-Agent: VociCollector/1.0
X-Auth-Key: {api_key}
X-Auth-Date: {unix_timestamp}
Authorization: {sha1(apiKey + apiSecret + timestamp)}
```

**Key endpoints:**
```bash
APIKEY="your_key"
APISECRET="your_secret"
TIMESTAMP=$(date +%s)
AUTH=$(echo -n "${APIKEY}${APISECRET}${TIMESTAMP}" | sha1sum | awk '{print $1}')

# Search Italian podcasts
curl -s "https://api.podcastindex.org/api/1.0/search/byterm?q=italia&lang=it&max=100" \
  -H "User-Agent: VociCollector/1.0" \
  -H "X-Auth-Key: ${APIKEY}" \
  -H "X-Auth-Date: ${TIMESTAMP}" \
  -H "Authorization: ${AUTH}"

# Trending Italian podcasts
curl -s "https://api.podcastindex.org/api/1.0/podcasts/trending?lang=it&max=100" ...

# Recently updated Italian feeds
curl -s "https://api.podcastindex.org/api/1.0/recent/feeds?lang=it&max=100" ...

# New feeds in last 24h
curl -s "https://api.podcastindex.org/api/1.0/recent/newfeeds?lang=it&max=100" ...

# Bridge: lookup by iTunes ID (connect Apple Charts to RSS)
curl -s "https://api.podcastindex.org/api/1.0/podcasts/byitunesid?id=291100561" ...
```

Response includes: `feedUrl`, `title`, `description`, `language`, `episodeCount`, `itunesId`
Pagination: `max` (1-1000), `since` (unix timestamp), `start_at` (feed ID offset)

### 3. Apple Podcasts Charts (Top Shows Discovery)

Two-step process: get chart listings, then resolve RSS feed URLs.

**Step A — Get top 100 per genre (Italian store):**
```bash
# Top 100 Italian podcasts (all genres)
curl -sL "https://rss.applemarketingtools.com/api/v2/it/podcasts/top/100/podcasts.json"

# Top 100 by genre (19 genres = up to 1,900 unique podcasts)
curl -sL "https://rss.applemarketingtools.com/api/v2/it/podcasts/top/100/podcasts.json?genre=1489"
```

Genre IDs: 1489=News, 1488=True Crime, 1324=Cultura e societa, 1310=Musica, 1487=Storia, 1321=Economia, 1303=Umorismo

Returns: `id` (iTunes ID), `name`, `artistName`, `url` — but NOT the RSS feed URL.

**Step B — Resolve RSS feed URLs via iTunes Lookup:**
```bash
# Batch lookup (comma-separated IDs)
curl -s "https://itunes.apple.com/lookup?id=291100561,1628126740,1501956064&entity=podcast"
```

Returns: `feedUrl` (RSS URL), `collectionName`, `trackCount`, `artistName`
Rate limit: ~20 calls/minute.

**NOTE:** The iTunes Search API (`/search?term=...`) is currently unreliable (returns 404 for most queries). Do NOT rely on it.

### 4. Spotify (Discovery Only — No Audio)

Useful for finding show names, but audio is DRM-protected. Discover shows here, find their RSS feeds via Podcast Index.

```bash
# Requires OAuth Bearer token from developer.spotify.com
curl -s "https://api.spotify.com/v1/search?q=podcast+italiano&type=show&market=IT&limit=10&offset=0" \
  -H "Authorization: Bearer {token}"
```

Limit: 10 results per page, max offset 1000. Returns: `name`, `publisher`, `total_episodes`, `languages[]`

### 5. Listen Notes (Fallback)

```bash
curl -s "https://listen-api.listennotes.com/api/v2/search?q=italia&type=podcast&language=Italian&offset=0" \
  -H "X-ListenAPI-Key: {key}"
```

Free tier: 5 req/min, limited monthly quota. Good for finding RSS of specific shows you can't find elsewhere.

## Podcast Selection Criteria

Not all podcasts are useful. We need **multi-speaker conversation**, not monologues.

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

### Tools
- **aria2c** — parallel HTTP downloader, 16 connections per file, resume support
- **feedparser** (Python) — robust RSS parser for malformed feeds
- **aiohttp** (Python) — async HTTP for high-throughput scraping

### RSS Parsing → Bulk Download
```bash
# Parse RSS, extract MP3 URLs
curl -s "https://www.spreaker.com/show/4779077/episodes/feed" \
  | grep -oP 'enclosure url="\K[^"]+' \
  > urls.txt

# Download all episodes, 5 at a time
aria2c -i urls.txt -j 5 -d ./downloads/ --auto-file-renaming=true
```

### Python approach
```python
import feedparser

feed = feedparser.parse("https://example.com/feed.xml")
for entry in feed.entries:
    audio_url = entry.enclosures[0].href
    title = entry.title
    duration = entry.get("itunes_duration", "unknown")
```

### Rate Limiting
- Max 5 concurrent downloads per source domain
- 1-second delay between API requests to same host
- Respect rate limit headers
- ProtonVPN for IP rotation if needed
- Some CDN URLs are signed/expire — download promptly after fetching

### Gotchas
- Some RSS feeds only list last 100-300 episodes (truncated). Use Spreaker API for complete episode lists
- Signed CDN URLs (CloudFront, Akamai) may expire within hours — don't batch-fetch URLs then download later
- Many Italian podcasts host on Spreaker, Megaphone, Omny Studio, or Simplecast — enclosure URLs point to their CDNs

### Storage Layout
```
data/raw/
├── index.db                    # SQLite: all shows, episodes, state
├── shows/
│   ├── {show_id}/
│   │   ├── metadata.json       # Show-level metadata
│   │   ├── episodes/
│   │   │   ├── {ep_id}.mp3     # Raw audio
│   │   │   ├── {ep_id}.json    # Episode metadata
│   │   │   └── ...
│   │   └── ...
│   └── ...
└── failed/                     # Failed downloads for retry
```

### Deduplication
- Hash-based (audio fingerprint) to catch same episode across different feeds
- Title + duration matching as a fast pre-filter
- RSS feed URL deduplication across sources (same feed discovered via Apple, Podcast Index, and Spreaker)

## Discovery Pipeline

```
Step 1: Discover shows
    ├── Spreaker: search 20+ Italian keywords across 19 categories
    ├── Podcast Index: lang=it search + trending + recent
    ├── Apple Charts: top 100 per genre (19 genres) → iTunes Lookup for RSS
    └── Spotify: discover names → find RSS via Podcast Index

Step 2: Deduplicate by RSS feed URL
    → Unique show list with RSS URLs

Step 3: Fetch RSS feeds, extract metadata
    → Filter: language=it, multi-speaker heuristics, duration 30-120min

Step 4: Sample validation (optional)
    → Download 1-2 episodes per show, quick diarization check

Step 5: Bulk download all episodes from qualified shows
    → aria2c parallel download, progress tracked in SQLite
```

## Estimated Yield

| Source | Unique Shows | Avg Episodes | Avg Duration | Total Hours |
|--------|-------------|-------------|-------------|-------------|
| Spreaker (Italian) | ~1,500 | 80 | 45 min | ~4,500h |
| Podcast Index (it) | ~800 (new) | 60 | 50 min | ~2,400h |
| Apple Charts (it) | ~300 (new) | 120 | 55 min | ~1,650h |
| **Total estimated** | **~2,600** | | | **~8,500h** |

After deduplication and quality filtering (~25% loss), target yield is **~6,500h raw → ~5,000h usable**.

## Legal Considerations

- All podcasts are publicly distributed via RSS (designed for download)
- Audio is used for research purposes (dataset creation)
- No redistribution of raw audio — only derived transcripts
- Show attribution maintained in metadata
- Respect any explicit licensing in feed metadata
