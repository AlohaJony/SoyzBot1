import os
import time
import logging
from config import MAX_BOT_TOKEN, YANDEX_DISK_TOKEN, DONATE_URL
from max_client import MaxBotClient
from downloader import MediaDownloader
from yandex_disk import YandexDiskUploader
from utils import TempDir
import traceback

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
MARKER_FILE = os.path.join(BASE_DIR, "marker.txt")

def load_marker():
    if os.path.exists(MARKER_FILE):
        try:
            with open(MARKER_FILE, "r") as f:
                val = int(f.read().strip())
                logger.info(f"✅ Loaded marker: {val}")
                return val
        except Exception as e:
            logger.error(f"❌ Failed to parse marker file: {e}")
    # Если файла нет или ошибка, возвращаем маркер "5 минут назад"
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
    BOT_USERNAME = bot_info.get('username')  # добавьте эту строку
    logger.info(f"Bot ID: {BOT_ID}, username: @{BOT_USERNAME}")
except Exception as e:
    logger.error(f"Failed to get bot info: {e}")
    BOT_ID = None
    BOT_USERNAME = None

yandex = YandexDiskUploader(YANDEX_DISK_TOKEN) if YANDEX_DISK_TOKEN else None

user_state = {}  # chat_id -> state

def process_link(chat_id: int, link: str):
    max_bot.send_action(chat_id, "typing_on")
    temp = TempDir()
    downloader = MediaDownloader(temp.path)

    try:
        info = downloader.extract_info(link)
        logger.error(f"Duration from info: {info.get('duration')}")
        files_to_send = []
        description = downloader.get_description(info)
        logger.error("Starting loop over entries")
        # Логируем структуру для отладки (ключи и наличие entries)
        logger.error(f"Structure: _type={info.get('_type')}, keys={list(info.keys())}")
        if 'entries' in info:
            logger.error(f"Number of entries: {len(info['entries'])}")

        # Обработка в зависимости от типа контента
        if info.get('_type') == 'playlist' or 'entries' in info:
            entries = info.get('entries', [])
            logger.info(f"Processing playlist with {len(entries)} entries")
            # Это плейлист/карусель (Instagram пост с несколькими элементами)
            for entry in info['entries']:
                logger.error(f"Entry keys: {list(entry.keys())}")
                if not entry:
                    continue

                # Пытаемся скачать видео (если есть длительность или это видео)
                video_success = False
                if entry.get('duration') or entry.get('ext') in ('mp4', 'mov'):  # предположим, что видео
                    try:
                        video_file, _ = downloader.download_best_video(entry['webpage_url'])
                        files_to_send.append(("video", video_file))
                        video_success = True
                    except Exception as e:
                        logger.error(f"Failed to download video from entry: {e}")
                        # Неудача – пробуем изображение

                if not video_success:
                    # Пытаемся скачать изображение
                    img_url = None
                    # Прямая ссылка на изображение (если есть)
                    if entry.get('url') and entry.get('ext') in ('jpg', 'png', 'jpeg', 'webp'):
                        img_url = entry['url']
                    # Или используем последний thumbnail
                    elif entry.get('thumbnails'):
                        img_url = entry['thumbnails'][-1]['url']
                    # Или может быть поле 'thumbnail' напрямую
                    elif entry.get('thumbnail'):
                        img_url = entry['thumbnail']

                    if img_url:
                        img_path = downloader._download_image(img_url, f"image_{entry.get('id', 'unknown')}.jpg")
                        if img_path:
                            files_to_send.append(("image", img_path))
                        else:
                            logger.error(f"Failed to download image from {img_url}")
                    else:
                        logger.error(f"No image URL found for entry {entry.get('id', 'unknown')}")
                    
            # Одиночный пост
            if 'duration' in info:  # видео (даже если длительность 0, но скорее всего это видео)
                try:
                    video_file, _ = downloader.download_best_video(link)
                    if video_file and os.path.exists(video_file):
                        files_to_send.append(("video", video_file))
                    else:
                        logger.error(f"Video file not created for {link}")
                except Exception as e:
                    logger.error(f"Failed to download video: {e}")
            elif info.get('url') and info.get('ext') in ('jpg', 'png', 'jpeg'):
                # Прямая ссылка на изображение
                img_path = downloader._download_image(info['url'], f"image.{info['ext']}")
                if img_path:
                    files_to_send.append(("image", img_path))
            # Дополнительно: если есть thumbnails и нет видео, скачиваем как изображение
            elif info.get('thumbnails') and not files_to_send:
                thumb_url = info['thumbnails'][-1]['url']
                img_path = downloader._download_image(thumb_url, "thumbnail.jpg")
                if img_path:
                    files_to_send.append(("image", img_path))

        # Если ничего не найдено, но есть описание – отправляем только текст
        if not files_to_send and not description:
            max_bot.send_message(chat_id, "Не удалось найти медиа по вашей ссылке.")
            return

        if not files_to_send and not description:
            max_bot.send_message(chat_id, "Не удалось найти медиа по вашей ссылке.")
            return

        for file_type, file_path in files_to_send:
            # Получаем токен (с загрузкой на CDN внутри)
            try:
                token = max_bot.upload_file(file_path, file_type)
                if token is None:
                    logger.error("No token received, using fallback")
                    if yandex:
                        public_url = yandex.upload_file(file_path)
                        max_bot.send_message(chat_id, f"Не удалось отправить файл напрямую, скачайте с Яндекс.Диска:\n{public_url}")
                    else:
                        max_bot.send_message(chat_id, "Не удалось отправить файл.")
                    continue  # переходим к следующему файлу, если они есть
            except Exception as e:
                logger.error(f"Failed to upload {file_path} to MAX: {e}")
                if yandex:
                    try:
                        public_url = yandex.upload_file(file_path)
                        max_bot.send_message(
                            chat_id,
                            f"Не удалось отправить файл напрямую, скачайте с Яндекс.Диска:\n{public_url}"
                        )
                    except Exception as e2:
                        logger.error(f"Yandex fallback failed: {e2}")
                        max_bot.send_message(chat_id, "Ошибка при обработке файла.")
                continue

            # Токен получен, теперь пытаемся отправить сообщение с увеличивающимися паузами
            attachment = max_bot.build_attachment(file_type, token)
            max_retries = 5
            success = False
            for attempt in range(max_retries):
                try:
                    # Пауза растёт: 2, 4, 8, 16, 32 секунды
                    wait_time = 2 ** (attempt + 1)
                    time.sleep(wait_time)
            
                    caption = f"Скачано через @{BOT_USERNAME}" if BOT_USERNAME else "Скачано через бота"
                    max_bot.send_message(chat_id, caption, attachments=[attachment])
                    logger.error(f"Message sent successfully on attempt {attempt+1}")
                    success = True
                    break
                except Exception as e:
                    logger.error(f"Send attempt {attempt+1} failed: {e}")
                    # Если это последняя попытка, переходим к fallback
                    if attempt == max_retries - 1:
                        logger.error("All send attempts exhausted, using fallback")
                        if yandex:
                            try:
                                public_url = yandex.upload_file(file_path)
                                max_bot.send_message(
                                    chat_id,
                                    f"Не удалось отправить файл напрямую, скачайте с Яндекс.Диска:\n{public_url}"
                                )
                            except Exception as e2:
                                logger.error(f"Yandex fallback failed: {e2}")
                                max_bot.send_message(chat_id, "Ошибка при обработке файла.")
            # Если успешно, небольшая пауза перед следующим файлом
            if success:
                time.sleep(1)

        if description:
            if len(description) > 4000:
                description = description[:4000] + "..."
            max_bot.send_message(chat_id, description, format="html")

        donate_msg = (
            f"✅ Готово!\n\n"
            f"Если вам помог бот, поддержите проект:\n"
            f"{DONATE_URL}"
        )
        max_bot.send_message(chat_id, donate_msg)

    except Exception as e:
        logger.error(f"Error: {traceback.format_exc()}")
        max_bot.send_message(chat_id, "Произошла ошибка при обработке ссылки. Попробуйте другую.")
    finally:
        downloader.cleanup()

def handle_update(update):
    logger.error(f"UPDATE RECEIVED: {update}")
    update_type = update.get("update_type")
    if update_type == "message_created":
        msg = update.get("message", {})
        mid = msg.get("body", {}).get("mid")
        # Проверка на дубликат (опционально)
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
        # Игнорируем свои сообщения
        if sender_id == BOT_ID:
            logger.info(f"Ignoring message from self (sender_id={sender_id})")
            return
        if sender.get("is_bot"):
            logger.info("Ignoring message from another bot")
            return

        # Обработка команд и ссылок
        if text.startswith("http"):
            process_link(chat_id, text)
        elif text == "/start":
            welcome = (
                "Привет! Я бот для скачивания видео, изображений и описаний из постов.\n"
                "Просто отправь мне ссылку на пост, и я пришлю тебе контент."
            )
            max_bot.send_message(chat_id, welcome)
        else:
            max_bot.send_message(chat_id, "Отправьте ссылку для обработки или /start для начала.")

        # Добавляем mid в обработанные (после успешной обработки)
        if mid:
            processed_mids.add(mid)

    elif update_type == "bot_started":
        chat_id = update.get("chat_id")
        if chat_id:
            welcome = (
                "Привет! Я бот для скачивания видео, изображений и описаний из постов.\n"
                "Просто отправь мне ссылку на пост, и я пришлю тебе контент."
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
