import requests
import time
import logging
from typing import Optional, Dict, Any, List
from config import MAX_BOT_TOKEN, MAX_API_BASE

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
        # 1. Получаем URL для загрузки от API MAX
        params = {"type": file_type}
        upload_info = self._request("POST", "/uploads", params=params)
        upload_url = upload_info["url"]

        # 2. Загружаем файл на полученный URL, обязательно с токеном в заголовке
        with open(file_path, "rb") as f:
            files = {"data": f}
            headers = {"Authorization": self.token}  # <-- ЭТО КЛЮЧЕВОЕ
            resp = requests.post(upload_url, files=files, headers=headers)
        logger.error(f"Upload response status: {resp.status_code}, body: {resp.text}")
        print("Upload response status:", resp.status_code, "Body:", resp.text)
        resp.raise_for_status()  # если снова 400, здесь упадёт с ошибкой
        
        result = resp.json()

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
