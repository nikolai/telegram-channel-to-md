# telegram-channel-to-md

Downloads all messages and media from a Telegram channel and exports them as a single Markdown file.

## What it does

- Fetches every message from a channel (chronological order)
- Converts Telegram formatting (bold, italic, code blocks, blockquotes, spoilers, links) to standard Markdown
- Downloads attached media — photos, videos, audio, GIFs, documents — into a `resources/` folder
- Embeds images inline; links other files as attachments
- Skips already-downloaded media on re-runs (incremental updates)
- Saves everything to `<output_dir>/channel_messages.md`

## Requirements

Python 3.10+ (uses `X | Y` type union syntax and `list[tuple]` generics).

```bash
pip install -r requirements.txt
```

## Setup

1. Get your Telegram API credentials at <https://my.telegram.org/apps>
2. Create a `.env` file in the project root (or pass credentials via CLI flags):

```env
TELEGRAM_API_ID=12345678
TELEGRAM_API_HASH=your_api_hash_here
```

## Usage

```bash
python download_telegram_channel.py [OPTIONS]
```

### Options

| Flag | Description | Default |
|------|-------------|---------|
| `--api-id` | Telegram API ID | `$TELEGRAM_API_ID` |
| `--api-hash` | Telegram API Hash | `$TELEGRAM_API_HASH` |
| `--channel` | Channel URL or username | `CHANNEL_URL_REMOVED` |
| `--output` | Output directory | `telegram_backup` |
| `--limit` | Max messages to fetch | all |

### Examples

```bash
# Export your saved messages / personal channel
python download_telegram_channel.py --channel CHANNEL_URL_REMOVED

# Export a public channel, limit to last 100 messages
python download_telegram_channel.py --channel https://t.me/somechannel --limit 100

# Custom output directory, credentials via flags
python download_telegram_channel.py \
  --api-id 12345678 \
  --api-hash abcdef1234567890 \
  --channel https://t.me/mychannel \
  --output ./export
```

## Output structure

```
<output_dir>/
├── channel_messages.md   # all messages in Markdown
├── resources/            # downloaded media files
│   ├── photo_123_20240101_120000.jpg
│   ├── 456_video.mp4
│   └── ...
└── telegram_session.session  # auth session (gitignored)
```

## Authentication

On the first run the script will prompt for your phone number and a Telegram confirmation code. The session is saved to `telegram_session.session` inside the output directory so subsequent runs skip re-authentication.

> **Note:** the session file and all downloaded content are gitignored and will not be committed.

## Supported media types

| Type | Handling |
|------|----------|
| Photos | Downloaded as `.jpg`, embedded inline |
| Videos (mp4, mov) | Downloaded, linked as attachment |
| Audio (mp3, ogg) | Downloaded, linked as attachment |
| GIF / WebP | Downloaded, embedded inline |
| Documents / PDF | Downloaded, linked as attachment |
| Web page previews | URL + title appended to message text |
