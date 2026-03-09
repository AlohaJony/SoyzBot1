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
            logger.error(f"HTTP error {resp.status_code} for {method} {path}: {resp.text}")
            raise
        return resp.json()

    def get_me(self) -> Dict[str, Any]:
        return self._request("GET", "/me")

    # Long polling
    def get_updates(self, marker: Optional[int] = None, timeout: int = 30, limit: int = 100) -> Dict[str, Any]:
        logger.info(f"Calling get_updates with marker={marker}, timeout={timeout}")
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

    def delete_message(self, message_id: str, user_id: Optional[int] = None, chat_id: Optional[int] = None) -> bool:
        """
        Удаляет сообщение по его mid.
        Требуется указать либо user_id (для личного чата), либо chat_id (для группового).
        """
        if not (user_id or chat_id):
            raise ValueError("Either user_id or chat_id must be provided")
        params = {"message_id": message_id}
        if user_id:
            params["user_id"] = user_id
        if chat_id:
            params["chat_id"] = chat_id
        result = self._request("DELETE", "/messages", params=params)
        return result.get("success", False)

    # Загрузка файла
    def upload_file(self, file_path: str, file_type: str) -> Optional[str]:
        upload_info = self._request("POST", "/uploads", params={"type": file_type})
        upload_url = upload_info["url"]
        token_from_api = upload_info.get("token")  # для видео и аудио токен приходит здесь

        with open(file_path, "rb") as f:
            files = {"data": (file_path, f, "application/octet-stream")}
            resp = requests.post(upload_url, files=files, timeout=120)
            resp.raise_for_status()

        # Для видео/аудио возвращаем токен, полученный ранее (не ждём JSON)
        if file_type in ("video", "audio") and token_from_api:
            return token_from_api

        # Для изображений и файлов пытаемся извлечь токен из ответа
        try:
            result = resp.json()
            token = result.get('token')
            if not token and 'photos' in result:
                for photo in result['photos'].values():
                    if isinstance(photo, dict) and 'token' in photo:
                        token = photo['token']
                        break
            return token
        except ValueError:
            logger.error(f"CDN response not JSON: {resp.text[:200]}")
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
        logger.info(f"Sending message to chat {chat_id} with payload: {payload}")
    
        # Выполняем запрос
        result = self._request("POST", "/messages", params=params, json=payload)
    
        # Логируем результат
        logger.info(f"Send message result: {result}")
        return result
