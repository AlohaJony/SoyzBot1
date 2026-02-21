import time
import logging
from config import MAX_BOT_TOKEN, YANDEX_DISK_TOKEN, DONATE_URL
from max_client import MaxBotClient
from downloader import MediaDownloader
from yandex_disk import YandexDiskUploader
from utils import TempDir
import traceback

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

max_bot = MaxBotClient(MAX_BOT_TOKEN)
yandex = YandexDiskUploader(YANDEX_DISK_TOKEN) if YANDEX_DISK_TOKEN else None

user_state = {}  # chat_id -> state

def process_link(chat_id: int, link: str):
    max_bot.send_action(chat_id, "typing_on")
    temp = TempDir()
    downloader = MediaDownloader(temp.path)

    try:
        info = downloader.extract_info(link)
        files_to_send = []
        description = downloader.get_description(info)

        if info.get("is_live") is False and info.get("duration"):
            video_file, _ = downloader.download_best_video(link)
            files_to_send.append(("video", video_file))
            
        images = downloader.download_all_images(link)
        for img in images:
            files_to_send.append(("image", img))

        if not files_to_send and not description:
            max_bot.send_message(chat_id, "Не удалось найти медиа по вашей ссылке.")
            return

        for file_type, file_path in files_to_send:
            max_retries = 3
            success = False
            for attempt in range(max_retries):
                try:
                    token = max_bot.upload_file(file_path, file_type)
                    attachment = max_bot.build_attachment(file_type, token)
                    # Небольшая задержка, чтобы файл обработался на сервере MAX
                    time.sleep(5)
                    max_bot.send_message(chat_id, "", attachments=[attachment])
                    logger.info(f"Файл {file_path} успешно отправлен в MAX")
                    success = True
                    break  # выход из цикла попыток
                except Exception as e:
                    logger.error(f"Попытка {attempt+1}/{max_retries} для {file_path} не удалась: {e}")
                    if attempt < max_retries - 1:
                        time.sleep(3)  # ждём перед следующей попыткой
                    else:
                        # Последняя попытка провалилась – используем fallback
                        logger.error(f"Все попытки отправить {file_path} в MAX исчерпаны")
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
                        else:
                            max_bot.send_message(chat_id, "Не удалось отправить файл.")
            # Если успешно, можно добавить небольшую паузу перед следующим файлом
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
    update_type = update.get("update_type")
    if update_type == "message_created":
        msg = update.get("message", {})
        chat_id = msg.get("recipient", {}).get("chat_id") or msg.get("recipient", {}).get("user_id")
        if not chat_id:
            return
        text = msg.get("body", {}).get("text", "").strip()
        sender = msg.get("sender", {})
        if sender.get("is_bot"):
            return

        if text == "/start":
            welcome = (
                "Привет! Я бот для скачивания видео, изображений и описаний из постов.\n"
                "Просто отправь мне ссылку на пост, и я пришлю тебе контент."
            )
            max_bot.send_message(chat_id, welcome)
            user_state[chat_id] = "waiting_link"
        elif user_state.get(chat_id) == "waiting_link" and text.startswith("http"):
            process_link(chat_id, text)
            user_state[chat_id] = None
        else:
            max_bot.send_message(chat_id, "Отправьте ссылку для обработки или /start для начала.")

    elif update_type == "bot_started":
        chat_id = update.get("chat_id")
        if chat_id:
            welcome = (
                "Привет! Я бот для скачивания видео, изображений и описаний из постов.\n"
                "Просто отправь мне ссылку на пост, и я пришлю тебе контент."
            )
            max_bot.send_message(chat_id, welcome)
            user_state[chat_id] = "waiting_link"

def main():
    logger.info("Starting MAX bot (polling mode)...")
    marker = None
    while True:
        try:
            updates_data = max_bot.get_updates(marker=marker, timeout=30)
            updates = updates_data.get("updates", [])
            marker = updates_data.get("marker")
            for upd in updates:
                handle_update(upd)
        except Exception as e:
            logger.error(f"Updates loop error: {e}")
            time.sleep(5)

if __name__ == "__main__":
    main()
