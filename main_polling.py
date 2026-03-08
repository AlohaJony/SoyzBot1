import os
import time
import logging
import traceback
from config import MAX_BOT_TOKEN, YANDEX_DISK_TOKEN, DONATE_URL
from max_client import MaxBotClient
from downloader import MediaDownloader
from yandex_disk import YandexDiskUploader
from utils import TempDir

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MARKER_FILE = os.path.join(BASE_DIR, "marker.txt")

# Список поддерживаемых доменов
SUPPORTED_DOMAINS = [
    'youtube.com', 'youtu.be',
    'instagram.com',
    'pin.it', 'pinterest.com', 'pinterest.ru'
]

def is_supported_url(url: str) -> bool:
    url_lower = url.lower()
    for domain in SUPPORTED_DOMAINS:
        if domain in url_lower:
            return True
    return False

def load_marker():
    if os.path.exists(MARKER_FILE):
        try:
            with open(MARKER_FILE, "r") as f:
                val = int(f.read().strip())
                logger.info(f"✅ Loaded marker: {val}")
                return val
        except Exception as e:
            logger.error(f"❌ Failed to parse marker file: {e}")
    fallback = int(time.time() * 1000) - 5 * 60 * 1000
    logger.info(f"📁 Using fallback marker (5 minutes ago): {fallback}")
    return fallback

def save_marker(marker):
    with open(MARKER_FILE, "w") as f:
        f.write(str(marker))
    logger.info(f"💾 Saved marker: {marker}")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

processed_mids = set()
max_bot = MaxBotClient(MAX_BOT_TOKEN)

try:
    bot_info = max_bot.get_me()
    BOT_ID = bot_info['user_id']
    BOT_USERNAME = bot_info.get('username')
    logger.info(f"Bot ID: {BOT_ID}, username: @{BOT_USERNAME}")
except Exception as e:
    logger.error(f"Failed to get bot info: {e}")
    BOT_ID = None
    BOT_USERNAME = None

yandex = YandexDiskUploader(YANDEX_DISK_TOKEN) if YANDEX_DISK_TOKEN else None
user_state = {}

def process_link(chat_id: int, link: str):
    max_bot.send_action(chat_id, "typing_on")
    temp = TempDir()
    downloader = MediaDownloader(temp.path)

    files_to_send = []
    description = None

    try:
        # Получаем информацию о контенте (работает для YouTube, Instagram, Pinterest)
        info = downloader.extract_info(link)
        logger.error(f"Duration from info: {info.get('duration')}")
        description = downloader.get_description(info)

        # Определяем, плейлист (карусель) или одиночный пост
        entries = info.get('entries')
        if entries and isinstance(entries, list) and len(entries) > 0:
            logger.info(f"📦 Processing playlist with {len(entries)} entries")
            for idx, entry in enumerate(entries):
                logger.error(f"🔍 Entry {idx+1} keys: {list(entry.keys())}")
                if not entry:
                    continue

                # Получаем URL для скачивания (для видео)
                entry_url = entry.get('webpage_url') or entry.get('url')
                if not entry_url:
                    logger.error(f"❌ Entry {idx+1} has no webpage_url, skipping")
                    continue

                # Определяем, является ли элемент видео
                is_video = False
                if entry.get('duration'):
                    is_video = True
                elif entry.get('ext') in ('mp4', 'mov', 'm4a', 'webm'):
                    is_video = True
                elif entry.get('vcodec') and entry['vcodec'] != 'none':
                    is_video = True

                # Пытаемся скачать видео
                video_success = False
                if is_video:
                    try:
                        logger.info(f"🎬 Attempting to download video from entry {idx+1}")
                        video_file, _ = downloader.download_best_video(entry_url)
                        if video_file and os.path.exists(video_file):
                            files_to_send.append(("video", video_file))
                            logger.info(f"✅ Video from entry {idx+1} downloaded: {video_file}")
                            video_success = True
                        else:
                            logger.error(f"❌ Video file not created for entry {idx+1}")
                    except Exception as e:
                        logger.error(f"❌ Failed to download video from entry {idx+1}: {e}")

                # Если видео не удалось или это не видео, пробуем изображение
                if not video_success:
                    logger.info(f"🖼️ Attempting to download image from entry {idx+1}")
                    img_url = None
                    # Прямая ссылка на изображение
                    if entry.get('url') and entry.get('ext') in ('jpg', 'png', 'jpeg', 'webp'):
                        img_url = entry['url']
                    # Набор миниатюр
                    elif entry.get('thumbnails'):
                        img_url = entry['thumbnails'][-1]['url']
                    # Одиночная миниатюра
                    elif entry.get('thumbnail'):
                        img_url = entry['thumbnail']
                    # Другие возможные поля (для Instagram)
                    elif entry.get('display_url'):
                        img_url = entry['display_url']
                    elif entry.get('image_url'):
                        img_url = entry['image_url']

                    if img_url:
                        img_path = downloader._download_image(img_url, f"image_{entry.get('id', f'entry_{idx}')}.jpg")
                        if img_path and os.path.exists(img_path):
                            files_to_send.append(("image", img_path))
                            logger.info(f"✅ Image from entry {idx+1} downloaded: {img_path}")
                        else:
                            logger.error(f"❌ Failed to download image for entry {idx+1} from {img_url}")
                    else:
                        logger.error(f"❌ No image URL found for entry {idx+1}")

        else:
            # Одиночный пост
            logger.info("📄 Single post processing")
            if 'duration' in info:
                try:
                    video_file, _ = downloader.download_best_video(link)
                    if video_file and os.path.exists(video_file):
                        files_to_send.append(("video", video_file))
                        logger.info(f"✅ Video downloaded: {video_file}")
                    else:
                        logger.error("❌ Video file not created")
                except Exception as e:
                    logger.error(f"❌ Failed to download video: {e}", exc_info=True)
            elif info.get('url') and info.get('ext') in ('jpg', 'png', 'jpeg'):
                img_path = downloader._download_image(info['url'], f"image.{info['ext']}")
                if img_path and os.path.exists(img_path):
                    files_to_send.append(("image", img_path))
                    logger.info(f"✅ Image downloaded: {img_path}")
            elif info.get('thumbnails') and not files_to_send:
                thumb_url = info['thumbnails'][-1]['url']
                img_path = downloader._download_image(thumb_url, "thumbnail.jpg")
                if img_path and os.path.exists(img_path):
                    files_to_send.append(("image", img_path))
                    logger.info(f"✅ Thumbnail downloaded: {img_path}")

        # Проверка на наличие файлов или описания
        if not files_to_send and not description:
            max_bot.send_message(chat_id, f"❌ Не удалось скачать медиа, но пост доступен по ссылке:\n{link}")
            return

        logger.info(f"📦 Total files to send: {len(files_to_send)}")

        # --- Отправка файлов (общий код) ---
        for file_type, file_path in files_to_send:
            if not os.path.exists(file_path):
                logger.error(f"❌ File {file_path} does not exist, skipping")
                continue

            # Загрузка видео на Яндекс.Диск (для получения ссылки на оригинал)
            yandex_url = None
            if file_type == "video" and yandex is not None:
                try:
                    logger.info(f"📤 Загружаем видео на Яндекс.Диск: {file_path}")
                    yandex_url = yandex.upload_file(file_path)
                    logger.info(f"✅ Видео загружено на Яндекс.Диск: {yandex_url}")
                except Exception as e:
                    logger.error(f"❌ Ошибка загрузки на Яндекс.Диск: {e}")

            # Загрузка в MAX
            try:
                token = max_bot.upload_file(file_path, file_type)
                if token is None:
                    logger.error("⚠️ No token received, using fallback")
                    if yandex and os.path.exists(file_path):
                        try:
                            public_url = yandex.upload_file(file_path)
                            max_bot.send_message(chat_id, f"📎 Не удалось отправить файл напрямую, скачайте с Яндекс.Диска:\n{public_url}")
                        except Exception as e2:
                            logger.error(f"❌ Yandex fallback failed: {e2}")
                            max_bot.send_message(chat_id, "❌ Ошибка при обработке файла.")
                    else:
                        max_bot.send_message(chat_id, "❌ Не удалось отправить файл.")
                    continue
            except Exception as e:
                logger.error(f"❌ Failed to upload {file_path} to MAX: {e}")
                if yandex and os.path.exists(file_path):
                    try:
                        public_url = yandex.upload_file(file_path)
                        max_bot.send_message(chat_id, f"📎 Не удалось отправить файл напрямую, скачайте с Яндекс.Диска:\n{public_url}")
                    except Exception as e2:
                        logger.error(f"❌ Yandex fallback failed: {e2}")
                        max_bot.send_message(chat_id, "❌ Ошибка при обработке файла.")
                continue

            # Формируем подпись
            caption = f"📥 Скачано через @{BOT_USERNAME}" if BOT_USERNAME else "📥 Скачано через бота"
            if yandex_url:
                caption += f"\n🔗 **Ссылка на оригинал (без сжатия):** {yandex_url}"

            # Отправка с подписью (с повторными попытками)
            attachment = max_bot.build_attachment(file_type, token)
            max_retries = 5
            success = False
            for attempt in range(max_retries):
                try:
                    wait_time = 2 ** (attempt + 1)
                    time.sleep(wait_time)
                    max_bot.send_message(chat_id, caption, attachments=[attachment])
                    logger.info(f"✅ Message sent successfully on attempt {attempt+1}")
                    success = True
                    break
                except Exception as e:
                    logger.error(f"⚠️ Send attempt {attempt+1} failed: {e}")
                    if attempt == max_retries - 1:
                        logger.error("❌ All send attempts exhausted, using fallback")
                        if yandex and os.path.exists(file_path):
                            try:
                                public_url = yandex.upload_file(file_path)
                                max_bot.send_message(chat_id, f"📎 Не удалось отправить файл напрямую, скачайте с Яндекс.Диска:\n{public_url}")
                            except Exception as e2:
                                logger.error(f"❌ Yandex fallback failed: {e2}")
                                max_bot.send_message(chat_id, "❌ Ошибка при обработке файла.")
            if success:
                time.sleep(1)

        # --- Отправка описания и доната ---
        if description:
            if len(description) > 4000:
                description = description[:4000] + "..."
            max_bot.send_message(chat_id, description, format="html")
            logger.info("📝 Description sent")

        donate_button = {
            "type": "inline_keyboard",
            "payload": {
                "buttons": [
                    [
                        {
                            "type": "link",
                            "text": "💰 Поддержать проект",
                            "url": DONATE_URL
                        }
                    ]
                ]
            }
        }
        max_bot.send_message(chat_id, "✅ <b>Готово!</b>\n\nЕсли вам помог бот, поддержите проект:",
                             format="html", attachments=[donate_button])
        logger.info("❤️ Donate message sent")

    except Exception as e:
        logger.error(f"🔥 Error: {traceback.format_exc()}")
        max_bot.send_message(chat_id, "❌ Произошла ошибка при обработке ссылки. Попробуйте другую.")
    finally:
        downloader.cleanup()
        logger.info("🧹 Temporary files cleaned up")

def handle_update(update):
    logger.error(f"UPDATE RECEIVED: {update}")
    update_type = update.get("update_type")
    if update_type == "message_created":
        msg = update.get("message", {})
        mid = msg.get("body", {}).get("mid")
        if mid and mid in processed_mids:
            logger.info(f"Message {mid} already processed, skipping")
            return

        chat_id = msg.get("recipient", {}).get("chat_id") or msg.get("recipient", {}).get("user_id")
        if not chat_id:
            logger.error("No chat_id in message")
            return
        text = msg.get("body", {}).get("text", "").strip()
        sender = msg.get("sender", {})
        if not sender:
            logger.error("No sender in message")
            return
        sender_id = sender.get("user_id")
        if sender_id is None:
            logger.error("sender_id is None")
            return
        if sender_id == BOT_ID:
            logger.info(f"Ignoring message from self (sender_id={sender_id})")
            return
        if sender.get("is_bot"):
            logger.info("Ignoring message from another bot")
            return

        # Обработка команд и ссылок
        if text.startswith("http"):
            if not is_supported_url(text):
                unsupported_msg = (
                    "⛔️ Вы прислали ссылку, которая не поддерживается!\n\n"
                    "**Что поддерживается?**\n\n"
                    "📸 **Instagram**\nПоддерживается: фото, видео.\n\n"
                    "📌 **Pinterest**\nПоддерживается: фото и видео.\n\n"
                    "▶️ **YouTube**\nПоддерживается: видео."
                )
                max_bot.send_message(chat_id, unsupported_msg)
                return
            process_link(chat_id, text)
        elif text == "/start":
            welcome = (
                "Добро пожаловать в СОЮЗ! 👋\n"
                "Отправьте мне ссылку на пост из Instagram*, Pinterest или на видео с YouTube, и я выгружу для вас фото, видео или содержимое поста прямо сюда — быстро, чётко и без лишней бюрократии 📲\n\n"
                "*Instagram является продуктом компании Meta, которая признана в России экстремистской организацией."
            )
            max_bot.send_message(chat_id, welcome)
        else:
            max_bot.send_message(chat_id, "Отправьте ссылку для обработки или /start для начала.")

        if mid:
            processed_mids.add(mid)

    elif update_type == "bot_started":
        chat_id = update.get("chat_id")
        if chat_id:
            welcome = (
                "Добро пожаловать в СОЮЗ! 👋\n"
                "Отправьте мне ссылку на пост из Instagram*, Pinterest или на видео с YouTube, и я выгружу для вас фото, видео или содержимое поста прямо сюда — быстро, чётко и без лишней бюрократии 📲\n\n"
                "*Instagram является продуктом компании Meta, которая признана в России экстремистской организацией."
            )
            max_bot.send_message(chat_id, welcome)

def main():
    logger.info("Starting MAX bot (polling mode)...")
    marker = load_marker()
    try:
        with open(MARKER_FILE, "a") as f:
            f.write("")
        logger.info(f"✅ Marker file is writable: {MARKER_FILE}")
    except Exception as e:
        logger.error(f"❌ Cannot write marker file: {e}")

    while True:
        try:
            updates_data = max_bot.get_updates(marker=marker, timeout=30)
            updates = updates_data.get("updates", [])
            new_marker = updates_data.get("marker")
            if new_marker is not None:
                marker = new_marker
                save_marker(marker)
            for upd in updates:
                handle_update(upd)
        except Exception as e:
            logger.error(f"Updates loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
