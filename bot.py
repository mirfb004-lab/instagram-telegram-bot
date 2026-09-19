import asyncio
import csv
import datetime
import logging
import os
import random
import tempfile
from functools import wraps
from pathlib import Path

from tabulate import tabulate
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, MessageHandler, filters

import cloudinary_upload
import database as db
import scraper

# Railway only needs these two bootstrap values. All other settings are managed in Telegram.
ADMIN_USER_ID = int(os.getenv("ADMIN_USER_ID", "123456789"))
BOT_TOKEN = os.getenv("BOT_TOKEN", "YOUR_TELEGRAM_BOT_TOKEN")
DEFAULT_MAX_EXPORT_LIMIT = 500
EXPORT_DIR = Path("exports")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def restricted(func):
    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not update.effective_user or update.effective_user.id != ADMIN_USER_ID:
            if update.message:
                await update.message.reply_text("Unauthorized.")
            return
        return await func(update, context)
    return wrapper


def cookie_sources() -> list[tuple[str, str]]:
    return scraper.cookie_sources(
        db.get_setting("cookies"),
        [db.get_setting(f"cookies_backup_{i}") for i in range(1, 4)],
    )


def max_export_limit() -> int:
    try:
        return max(1, int(db.get_setting("max_export_limit", str(DEFAULT_MAX_EXPORT_LIMIT))))
    except ValueError:
        return DEFAULT_MAX_EXPORT_LIMIT


def parse_schedule(value: str) -> datetime.time:
    hour, minute = map(int, value.split(":", 1))
    return datetime.time(hour=hour, minute=minute, tzinfo=datetime.timezone.utc)


@restricted
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Instagram Performance Tracker Bot\n\n"
        "SETUP (all managed here):\n"
        "/setcookies <cookie string>\n"
        "/setbackup1 <cookie string>\n/setbackup2 <cookie string>\n/setbackup3 <cookie string>\n"
        "/setcloudinary <cloud name> <unsigned upload preset>\n"
        "/setlimit <number>\n\n"
        "TRACKING:\n"
        "/addaccounts <user1, user2>\n/removeaccounts <user1, user2>\n/listaccounts\n"
        "/test <username or profile link>\n/runnow\n/report\n"
        "/export <username or profile link> [limit]\n\n"
        "CONTROL:\n/status\n/setschedule <HH:MM>\n/clearcookies [primary|backup1|backup2|backup3|all]\n\n"
        "Upload accounts.txt, cookies.txt, cookies_backup1.txt, cookies_backup2.txt, or cookies_backup3.txt."
    )


async def save_cookie_command(update: Update, context: ContextTypes.DEFAULT_TYPE, key: str, label: str):
    value = " ".join(context.args).strip()
    if not value:
        await update.message.reply_text(f"Usage: /{label} sessionid=...; ds_user_id=...")
        return
    if not scraper.parse_cookie_string(value):
        await update.message.reply_text("Invalid cookie format. Use name=value; name2=value2")
        return
    db.set_setting(key, value)
    await update.message.reply_text(f"{label} cookies saved securely in the bot database.")


@restricted
async def set_cookies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_cookie_command(update, context, "cookies", "setcookies")


@restricted
async def set_backup1(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_cookie_command(update, context, "cookies_backup_1", "setbackup1")


@restricted
async def set_backup2(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_cookie_command(update, context, "cookies_backup_2", "setbackup2")


@restricted
async def set_backup3(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_cookie_command(update, context, "cookies_backup_3", "setbackup3")


@restricted
async def set_cloudinary(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if len(context.args) != 2:
        await update.message.reply_text("Usage: /setcloudinary <cloud name> <unsigned upload preset>")
        return
    cloud_name, preset = context.args
    db.set_setting("cloudinary_cloud_name", cloud_name)
    db.set_setting("cloudinary_upload_preset", preset)
    await update.message.reply_text("Cloudinary configured. You can now use /export.")


@restricted
async def set_limit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        value = int(context.args[0])
        if not 1 <= value <= 5000:
            raise ValueError
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /setlimit <number from 1 to 5000>")
        return
    db.set_setting("max_export_limit", str(value))
    await update.message.reply_text(f"Maximum export limit set to {value}.")


@restricted
async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    configured = [name for name, _ in cookie_sources()]
    schedule = db.get_setting("schedule_utc", "08:00")
    cloud = bool(db.get_setting("cloudinary_cloud_name") and db.get_setting("cloudinary_upload_preset"))
    await update.message.reply_text(
        "Bot status\n"
        f"Accounts: {db.count_accounts()}\n"
        f"Cookie sources ready: {', '.join(configured) if configured else 'none'}\n"
        f"Cloudinary: {'configured' if cloud else 'not configured'}\n"
        f"Export limit: {max_export_limit()}\n"
        f"Daily schedule: {schedule} UTC\n"
        f"Database: {db.DB_FILE}"
    )


@restricted
async def clear_cookies(update: Update, context: ContextTypes.DEFAULT_TYPE):
    target = context.args[0].lower() if context.args else "all"
    keys = {"primary": ["cookies"], "backup1": ["cookies_backup_1"], "backup2": ["cookies_backup_2"], "backup3": ["cookies_backup_3"], "all": ["cookies", "cookies_backup_1", "cookies_backup_2", "cookies_backup_3"]}
    if target not in keys:
        await update.message.reply_text("Usage: /clearcookies [primary|backup1|backup2|backup3|all]")
        return
    for key in keys[target]:
        db.delete_setting(key)
    await update.message.reply_text(f"Cleared {target} cookie setting(s).")


@restricted
async def add_accounts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /addaccounts handle1, handle2, handle3")
        return
    items = [x.strip() for x in " ".join(context.args).replace(",", " ").split() if x.strip()]
    db.add_accounts(items)
    await update.message.reply_text(f"Processed {len(items)} account names.")


@restricted
async def remove_accounts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /removeaccounts handle1, handle2")
        return
    items = [x.strip() for x in " ".join(context.args).replace(",", " ").split() if x.strip()]
    removed = db.remove_accounts(items)
    await update.message.reply_text(f"Removed {removed} account(s).")


@restricted
async def list_accounts_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    accounts = db.get_all_accounts()
    if not accounts:
        await update.message.reply_text("Account watchlist is empty.")
        return
    text = "Accounts ({}):\n{}".format(len(accounts), "\n".join(f"{i}. @{name}" for i, name in enumerate(accounts, 1)))
    for start in range(0, len(text), 3800):
        await update.message.reply_text(text[start:start + 3800])


@restricted
async def handle_document(update: Update, context: ContextTypes.DEFAULT_TYPE):
    doc = update.message.document
    name = (doc.file_name or "").lower()
    if not (name.endswith(".txt") or name.endswith(".json")):
        await update.message.reply_text("Upload a .txt account list or cookie export file.")
        return
    file = await doc.get_file()
    content = (await file.download_as_bytearray()).decode("utf-8")
    if "cookie" in name:
        slot = next((str(i) for i in range(1, 4) if f"backup{i}" in name or f"backup_{i}" in name), None)
        key = f"cookies_backup_{slot}" if slot else "cookies"
        db.set_setting(key, content)
        await update.message.reply_text(f"Cookie file saved as {'backup ' + slot if slot else 'primary'}.")
    else:
        accounts = [line.strip() for line in content.splitlines() if line.strip()]
        db.add_accounts(accounts)
        await update.message.reply_text(f"Imported {len(accounts)} account names.")


@restricted
async def test_account(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /test <username or Instagram profile link>")
        return
    target = scraper.normalize_username(context.args[0])
    sources = cookie_sources()
    if not sources:
        await update.message.reply_text("No cookies configured. Set primary plus up to three backups.")
        return
    status_msg = await update.message.reply_text(f"Fetching @{target} with failover...")
    try:
        data, source = await asyncio.to_thread(scraper.get_profile_data_with_failover, target, sources)
        await status_msg.edit_text(f"@{target}: {data['followers']:,} followers (cookie source: {source})")
    except Exception as exc:
        await status_msg.edit_text(f"Test failed: {str(exc)[:800]}")


@restricted
async def export_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Usage: /export <username or profile link> [limit]")
        return
    target = context.args[0]
    try:
        limit = int(context.args[1]) if len(context.args) > 1 else 50
        if not 1 <= limit <= max_export_limit():
            raise ValueError(f"limit must be between 1 and {max_export_limit()}")
    except ValueError as exc:
        await update.message.reply_text(f"Invalid limit: {exc}")
        return
    sources = cookie_sources()
    cloud_name = db.get_setting("cloudinary_cloud_name")
    preset = db.get_setting("cloudinary_upload_preset")
    if not sources:
        await update.message.reply_text("No cookies configured.")
        return
    if not cloud_name or not preset:
        await update.message.reply_text("Cloudinary is not configured. Use /setcloudinary first.")
        return
    status_msg = await update.message.reply_text(f"Collecting up to {limit} media items...")
    try:
        records, source = await asyncio.to_thread(scraper.collect_media_with_failover, target, limit, sources)
        if not records:
            await status_msg.edit_text("No accessible posts, videos, or reels were returned.")
            return
        active_cookies = dict(sources)[source]
        EXPORT_DIR.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="instagram-export-") as temp_dir:
            for index, record in enumerate(records, start=1):
                suffix = ".mp4" if record["media_type"] == "video/reel" else ".jpg"
                local_path = os.path.join(temp_dir, f"media-{index}{suffix}")
                await asyncio.to_thread(scraper.download_media, record["media_url"], active_cookies, local_path)
                record["cloudinary_url"] = await asyncio.to_thread(cloudinary_upload.upload_file, local_path, cloud_name, preset)
                record.pop("media_url", None)
            csv_path = EXPORT_DIR / f"instagram_{scraper.normalize_username(target)}_{datetime.datetime.now(datetime.timezone.utc):%Y%m%dT%H%M%SZ}.csv"
            fields = ["username", "caption", "cloudinary_url", "original_post_url", "engagements", "likes", "comments", "plays", "duration", "date_posting", "media_type"]
            with csv_path.open("w", newline="", encoding="utf-8-sig") as output:
                writer = csv.DictWriter(output, fieldnames=fields, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(records)
        await status_msg.edit_text(f"Exported {len(records)} items using {source}. Sending CSV...")
        with csv_path.open("rb") as document:
            await update.message.reply_document(document=document, filename=csv_path.name, caption="Instagram media export with Cloudinary URLs.")
    except Exception as exc:
        logger.exception("Media export failed")
        await status_msg.edit_text(f"Export failed: {str(exc)[:1000]}")


async def execute_batch_cycle(context: ContextTypes.DEFAULT_TYPE, chat_id: int):
    sources = cookie_sources()
    if not sources:
        await context.bot.send_message(chat_id=chat_id, text="Cannot run: no cookie source configured.")
        return
    accounts = db.get_all_accounts()
    if not accounts:
        await context.bot.send_message(chat_id=chat_id, text="Account watchlist is empty.")
        return
    status_msg = await context.bot.send_message(chat_id=chat_id, text=f"Starting cycle for {len(accounts)} accounts. Progress: 0/{len(accounts)}")
    success, failed = 0, 0
    for idx, user in enumerate(accounts, start=1):
        try:
            data, source = await asyncio.to_thread(scraper.get_profile_data_with_failover, user, sources)
            db.update_account_stats(user, data["followers"], status=f"OK:{source}")
            success += 1
        except Exception as exc:
            logger.warning("Error on %s: %s", user, exc)
            db.mark_account_failed(user, str(exc))
            failed += 1
        if idx % 20 == 0 or idx == len(accounts):
            await status_msg.edit_text(f"Scanning accounts: {idx}/{len(accounts)} (Errors: {failed})")
        await asyncio.sleep(random.uniform(2.0, 4.0))
    await status_msg.edit_text(f"Scan complete: {success} successful, {failed} failed.")
    await send_leaderboard_report(context, chat_id, "Instagram Daily Report")


async def send_leaderboard_report(context: ContextTypes.DEFAULT_TYPE, chat_id: int, title: str = "Performance Report"):
    data = db.get_leaderboard_data()
    if not data:
        await context.bot.send_message(chat_id=chat_id, text="No data available yet.")
        return
    rows = []
    for user, cur, net, status in data[:50]:
        rows.append([f"{user[:11]}{' [error]' if not str(status).startswith('OK') else ''}", f"{cur:,}", f"+{net}" if net > 0 else str(net)])
    await context.bot.send_message(chat_id=chat_id, text=f"{title}\n\n{tabulate(rows, headers=['User', 'Followers', '+/-'], tablefmt='simple')}")


@restricted
async def run_now(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await execute_batch_cycle(context, update.effective_chat.id)


@restricted
async def report_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await send_leaderboard_report(context, update.effective_chat.id, "Latest Leaderboard")


async def scheduled_daily_job(context: ContextTypes.DEFAULT_TYPE):
    await execute_batch_cycle(context, ADMIN_USER_ID)


@restricted
async def set_schedule(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        time_value = context.args[0]
        parsed = parse_schedule(time_value)
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /setschedule 08:30 (UTC time)")
        return
    db.set_setting("schedule_utc", parsed.strftime("%H:%M"))
    for job in context.job_queue.get_jobs_by_name("daily_tracker"):
        job.schedule_removal()
    context.job_queue.run_daily(scheduled_daily_job, time=parsed, name="daily_tracker")
    await update.message.reply_text(f"Daily scan scheduled for {parsed.strftime('%H:%M')} UTC.")


def register_handlers(app):
    handlers = {
        "start": start, "setcookies": set_cookies, "setbackup1": set_backup1,
        "setbackup2": set_backup2, "setbackup3": set_backup3, "setcloudinary": set_cloudinary,
        "setlimit": set_limit, "status": status_cmd, "clearcookies": clear_cookies,
        "addaccounts": add_accounts_cmd, "removeaccounts": remove_accounts_cmd,
        "listaccounts": list_accounts_cmd, "test": test_account, "export": export_profile,
        "runnow": run_now, "report": report_cmd, "setschedule": set_schedule,
    }
    for command, handler in handlers.items():
        app.add_handler(CommandHandler(command, handler))
    app.add_handler(MessageHandler(filters.Document.ALL, handle_document))


def main():
    if BOT_TOKEN == "YOUR_TELEGRAM_BOT_TOKEN":
        raise RuntimeError("Set BOT_TOKEN before starting the bot")
    db.init_db()
    app = ApplicationBuilder().token(BOT_TOKEN).build()
    register_handlers(app)
    try:
        scheduled_time = parse_schedule(db.get_setting("schedule_utc", "08:00"))
    except ValueError:
        scheduled_time = datetime.time(8, 0, tzinfo=datetime.timezone.utc)
    app.job_queue.run_daily(scheduled_daily_job, time=scheduled_time, name="daily_tracker")
    app.run_polling()


if __name__ == "__main__":
    main()
