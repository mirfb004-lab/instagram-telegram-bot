# Instagram Telegram Bot

A Telegram-controlled Instagram profile tracker and media exporter.

## Railway deployment

The application requires only these two Railway variables to bootstrap:

```text
BOT_TOKEN=your_telegram_bot_token
ADMIN_USER_ID=your_numeric_telegram_user_id
```

`ADMIN_USER_ID` is the numeric Telegram ID of the one administrator allowed to control the bot. It is intentionally required for security; the bot cannot safely discover an administrator from an unknown Telegram message.

Deploy the repository as a Railway worker/service using the included `Procfile`:

```text
worker: python bot.py
```

For persistence across redeployments, attach a Railway volume mounted at `/app/data`. The bot automatically uses `/app/data/tracker.db` when that directory exists. Without a volume, cookies, accounts, schedules, and follower history can be lost when Railway replaces the container.

## First-time setup from Telegram

Send `/start`, then configure everything else through the bot:

```text
/setcookies sessionid=...; ds_user_id=...
/setbackup1 sessionid=...; ds_user_id=...
/setbackup2 sessionid=...; ds_user_id=...
/setbackup3 sessionid=...; ds_user_id=...
/setcloudinary cloud_name unsigned_upload_preset
/setlimit 500
/setschedule 08:00
```

The primary cookie is tried first. The three backup cookies are automatically tried next when a request fails because of invalid cookies, rate limiting, or a request error.

Cloudinary setup requires an unsigned upload preset in the Cloudinary dashboard. The cloud name and preset are entered through Telegram and saved in the bot database; they do not need to be Railway variables.

## Telegram commands

### Configuration and control

```text
/start
/status
/setcloudinary <cloud name> <unsigned upload preset>
/setlimit <1-5000>
/setschedule <HH:MM>
/clearcookies [primary|backup1|backup2|backup3|all]
```

### Cookies

```text
/setcookies <cookie string>
/setbackup1 <cookie string>
/setbackup2 <cookie string>
/setbackup3 <cookie string>
```

You can also upload these files directly to the bot:

- `cookies.txt` or `cookies.json` — primary cookies
- `cookies_backup1.txt` or `cookies_backup1.json` — backup 1
- `cookies_backup2.txt` or `cookies_backup2.json` — backup 2
- `cookies_backup3.txt` or `cookies_backup3.json` — backup 3

Raw semicolon-separated cookies, JSON browser exports, and Netscape cookie exports are supported.

### Accounts and follower tracking

```text
/addaccounts user1, user2
/removeaccounts user1, user2
/listaccounts
/test username_or_profile_link
/runnow
/report
```

Upload an `accounts.txt` file containing one username or profile link per line to import accounts.

### Media export

```text
/export username_or_profile_link [limit]
```

The bot collects accessible posts, videos, and reels, downloads each item, uploads it to Cloudinary, and sends a CSV file back to Telegram. CSV columns include caption, Cloudinary URL, original post URL, total engagements, likes, comments, plays/views, video duration, posting date, and media type.

The limit is controlled by `/setlimit` and is bounded to protect the Railway worker. Instagram’s web endpoints are unofficial and can change or return only media visible to the authenticated session; no scraper can guarantee every historical item.

## Security notes

Never commit `tracker.db`, cookie values, bot tokens, or Cloudinary configuration to GitHub. Cookie commands are sensitive because Telegram messages may remain in chat history; uploading a cookie file and deleting the message afterward is safer. Use a private administrator chat and rotate cookies if they are exposed.

The repository intentionally contains no credentials, database, generated exports, or local Python cache files.
