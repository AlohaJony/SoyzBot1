import requests
import time
import logging
import os
import shutil
from typing import Optional, Dict, Any, List
from config import MAX_BOT_TOKEN, MAX_API_BASE
from requests.exceptions import RequestException

logger = logging.getLogger(__name__)


class MaxBotClient:
    def __init__(self, token: str):
        self.token = token
        self.base_url = MAX_API_BASE
        self.session = requests.Session()
        self.session.headers.update({"Authorization": token})

    def _request(self, method: str, path: str, **kwargs) -> Dict[str, Any]:
        url = f"{self.base_url}{path}"
        resp = self.session.request(method, url, **kwargs)
        resp.raise_for_status()
        return resp.json()

    def get_me(self) -> Dict[str, Any]:
        return self._request("GET", "/me")

    # Long polling
    def get_updates(self, marker: Optional[int] = None, timeout: int = 30, limit: int = 100) -> Dict[str, Any]:
        params = {"timeout": timeout, "limit": limit}
        if marker:
            params["marker"] = marker
        return self._request("GET", "/updates", params=params)

    # Webhook: подписка
    def set_webhook(self, url: str, secret: Optional[str] = None, update_types: Optional[List[str]] = None) -> bool:
        payload = {"url": url}
        if secret:
            payload["secret"] = secret
        if update_types:
            payload["update_types"] = update_types
        result = self._request("POST", "/subscriptions", json=payload)
        return result.get("success", False)

    def delete_webhook(self, url: str) -> bool:
        result = self._request("DELETE", "/subscriptions", params={"url": url})
        return result.get("success", False)

    # Действия
    def send_action(self, chat_id: int, action: str) -> bool:
        path = f"/chats/{chat_id}/actions"
        resp = self._request("POST", path, json={"action": action})
        return resp.get("success", False)

    # Загрузка файла
    def upload_file(self, file_path: str, file_type: str) -> Optional[str]:
        import os
        import shutil
        import time
        from requests.exceptions import RequestException

        # Логируем размер файла
        file_size = os.path.getsize(file_path)
        logger.error(f"Начинаем загрузку файла: {file_path}, размер: {file_size} байт, тип: {file_type}")

        # 1. Получаем URL для загрузки от API MAX
        params = {"type": file_type}
        upload_info = self._request("POST", "/uploads", params=params)
        upload_url = upload_info["url"]
        logger.error(f"Получен upload_url: {upload_url}")

        # 2. Переименовываем файл в простое имя, чтобы избежать проблем со спецсимволами
        safe_filename = "video.mp4"  # для видео; для других типов можно сделать универсально
        if file_type != "video":
            # Для изображений, файлов и т.д. можно использовать оригинальное расширение
            ext = os.path.splitext(file_path)[1]
            safe_filename = f"file{ext}"
        safe_path = os.path.join(os.path.dirname(file_path), safe_filename)
        shutil.copy2(file_path, safe_path)
        logger.error(f"Создана копия с безопасным именем: {safe_path}")

        # 3. Загружаем файл на CDN с повторными попытками
        max_upload_retries = 3
        for attempt in range(max_upload_retries):
            try:
                with open(safe_path, "rb") as f:
                    files = {"data": f}
                    # Важно: НЕ передаём заголовок Authorization, только Content-Type (опционально)
                    headers = {"Content-Type": "multipart/form-data"}  # можно добавить, но не обязательно
                    resp = requests.post(upload_url, files=files, headers=headers, timeout=60)

                logger.error(f"Попытка {attempt+1}/{max_upload_retries}: статус {resp.status_code}")
                logger.error(f"Тело ответа: {resp.text}")

                resp.raise_for_status()
                result = resp.json()
                logger.error(f"Загрузка успешна, получен результат: {result}")

                # 4. Удаляем временную копию
                os.remove(safe_path)
                break  # выход из цикла попыток

            except RequestException as e:
                logger.error(f"Ошибка при загрузке (попытка {attempt+1}): {e}")
                if attempt == max_upload_retries - 1:
                    # Последняя попытка не удалась – пробуем оригинальный файл (на всякий случай) или падаем
                    logger.error("Все попытки загрузки на CDN исчерпаны")
                    # Можно попробовать загрузить оригинальный файл как fallback
                    try:
                        with open(file_path, "rb") as f:
                            files = {"data": f}
                            resp = requests.post(upload_url, files=files, timeout=60)
                        resp.raise_for_status()
                        result = resp.json()
                        logger.error("Загрузка оригинального файла неожиданно удалась")
                        os.remove(safe_path)  # всё равно удалим временный
                        break
                    except Exception as e2:
                        logger.error(f"Fallback тоже не удался: {e2}")
                        os.remove(safe_path)
                        raise  # пробрасываем исключение дальше
                else:
                    # Ждём перед следующей попыткой (экспоненциальная задержка)
                    wait_time = 2 ** attempt  # 1, 2, 4 секунды
                    logger.error(f"Повторная попытка через {wait_time} секунд")
                    time.sleep(wait_time)
            except Exception as e:
                # Другие ошибки (например, проблемы с файлом)
                logger.error(f"Неожиданная ошибка: {e}")
                os.remove(safe_path)
                raise
        else:
            # Если цикл завершился без break (все попытки провалились)
            os.remove(safe_path)
            raise Exception("Не удалось загрузить файл на CDN после нескольких попыток")

        # 5. Возвращаем токен в зависимости от типа файла
        if file_type in ("video", "audio"):
            return result.get("token")
        else:
            return result.get("token") or result.get("photo_id")

    def build_attachment(self, file_type: str, token: str) -> Dict:
        return {"type": file_type, "payload": {"token": token}}

    def send_message(
        self,
        chat_id: int,
        text: str,
        attachments: Optional[List[Dict]] = None,
        format: Optional[str] = None,
        disable_link_preview: bool = False,
    ) -> Dict[str, Any]:
        payload = {"text": text, "attachments": attachments or []}
        if format:
            payload["format"] = format
        params = {"chat_id": chat_id, "disable_link_preview": str(disable_link_preview).lower()}
        return self._request("POST", "/messages", params=params, json=payload)
