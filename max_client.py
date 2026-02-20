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
        import time
        from requests.exceptions import RequestException

        file_size = os.path.getsize(file_path)
        logger.error(f"Uploading file: {os.path.basename(file_path)}, size: {file_size} bytes, type: {file_type}")

        # 1. Получаем upload_url от API MAX
        params = {"type": file_type}
        upload_info = self._request("POST", "/uploads", params=params)
        upload_url = upload_info["url"]
        logger.error(f"Upload URL: {upload_url}")

        # 2. Загружаем файл на CDN, максимально приближаясь к curl-примеру
        max_retries = 3
        for attempt in range(max_retries):
            try:
                with open(file_path, "rb") as f:
                    # Создаём файловый объект так, как это делает curl с -F "data=@file"
                    files = {"data": (os.path.basename(file_path), f, "application/octet-stream")}
                    # Важно: НЕ передаём никаких заголовков, кроме тех, что requests ставит сам
                    resp = requests.post(upload_url, files=files, timeout=60)

                logger.error(f"Attempt {attempt+1}: status {resp.status_code}")
                logger.error(f"Response body: {resp.text[:200]}")  # первые 200 символов

                resp.raise_for_status()
                result = resp.json()
                logger.error(f"Upload successful, result: {result}")

                # 3. Возвращаем токен
                if file_type in ("video", "audio"):
                    return result.get("token")
                else:
                    return result.get("token") or result.get("photo_id")

            except RequestException as e:
                logger.error(f"Upload attempt {attempt+1} failed: {e}")
                if attempt == max_retries - 1:
                    raise
                time.sleep(2 ** attempt)  # 1, 2, 4 seconds

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
