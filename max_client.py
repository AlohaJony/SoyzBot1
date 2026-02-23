import requests
import time
import logging
import os
import shutil
import xml.etree.ElementTree as ET
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
        try:
            resp.raise_for_status()
        except requests.HTTPError as e:
            # Здесь мы увидим, что именно возвращает MAX при 400
            logger.error(f"HTTP error {resp.status_code} for {method} {path}: {resp.text}")
            raise
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
        import time
        from requests.exceptions import RequestException
        import xml.etree.ElementTree as ET

        file_size = os.path.getsize(file_path)
        logger.error(f"Uploading file: {os.path.basename(file_path)}, size: {file_size} bytes, type: {file_type}")

        # 1. Получаем upload_url и, возможно, токен от API MAX
        params = {"type": file_type}
        upload_info = self._request("POST", "/uploads", params=params)
        logger.error(f"Full upload_info: {upload_info}")

        upload_url = upload_info["url"]
        # Для video/audio токен может быть уже здесь, сохраним его
        token_from_api = upload_info.get("token")

        # 2. Загружаем файл на CDN (обязательно для всех типов)
        max_retries = 2
        for attempt in range(max_retries):
            try:
                with open(file_path, "rb") as f:
                    files = {"data": (os.path.basename(file_path), f, "application/octet-stream")}
                    resp = requests.post(upload_url, files=files, timeout=60)

                logger.error(f"CDN upload attempt {attempt+1}: status {resp.status_code}")
                logger.error(f"Response headers: {dict(resp.headers)}")
                logger.error(f"Response body: {resp.text}")

                resp.raise_for_status()
                break  # успешно
            except RequestException as e:
                logger.error(f"CDN upload attempt {attempt+1} failed: {e}")
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)

        # 3. Теперь, когда файл загружен, возвращаем токен
        if file_type in ("video", "audio"):
            # Для видео/аудио используем токен, полученный от API
            if token_from_api:
                return token_from_api
            else:
                # Если токена почему-то нет, пробуем извлечь из ответа (маловероятно)
                try:
                    result = resp.json()
                    return result.get("token")
                except:
                    return None
        else:
            # Для image/file токен должен быть в ответе CDN (JSON)
            try:
                result = resp.json()
                logger.error(f"CDN response JSON: {result}")

                # Извлекаем токен из разных возможных структур
                token = None
                if "token" in result:
                    token = result["token"]
                elif "photos" in result and isinstance(result["photos"], dict):
                    # Ответ вида {"photos": {"some_key": {"token": "..."}}}
                    for photo_key, photo_val in result["photos"].items():
                        if isinstance(photo_val, dict) and "token" in photo_val:
                            token = photo_val["token"]
                            break
                elif "photo_id" in result:
                    token = result["photo_id"]
                else:
                    # Попробуем другие возможные поля (на всякий случай)
                    token = result.get("id") or result.get("url")

                if token:
                    logger.error(f"Extracted token for {file_type}: {token}")
                    return token
                else:
                    logger.error(f"Could not extract token from CDN response for {file_type}")
                    return None
            except ValueError:
                logger.error("CDN response is not JSON, cannot extract token")
                return None

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
    
        # Логируем, что отправляем
        logger.error(f"Sending message to chat {chat_id} with payload: {payload}")
    
        # Выполняем запрос
        result = self._request("POST", "/messages", params=params, json=payload)
    
        # Логируем результат
        logger.error(f"Send message result: {result}")
        return result
