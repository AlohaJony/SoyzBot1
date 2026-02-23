def upload_file(self, file_path: str, file_type: str) -> Optional[str]:
    import os
    import time
    from requests.exceptions import RequestException
    import xml.etree.ElementTree as ET

    if not os.path.exists(file_path):
        logger.error(f"File {file_path} does not exist, skipping")
        return None

    file_size = os.path.getsize(file_path)
    logger.error(f"Uploading file: {os.path.basename(file_path)}, size: {file_size} bytes, type: {file_type}")

    # 1. Получаем upload_url и, возможно, токен от API MAX
    params = {"type": file_type}
    upload_info = self._request("POST", "/uploads", params=params)
    logger.error(f"Full upload_info: {upload_info}")

    upload_url = upload_info["url"]
    token_from_api = upload_info.get("token")

    # 2. Загружаем файл на CDN (обязательно для всех типов)
    max_retries = 2
    resp = None
    for attempt in range(max_retries):
        try:
            with open(file_path, "rb") as f:
                files = {"data": (os.path.basename(file_path), f, "application/octet-stream")}
                resp = requests.post(upload_url, files=files, timeout=60)

            logger.error(f"CDN upload attempt {attempt+1}: status {resp.status_code}")
            logger.error(f"Response headers: {dict(resp.headers)}")
            logger.error(f"Response body: {resp.text}")

            resp.raise_for_status()
            break
        except RequestException as e:
            logger.error(f"CDN upload attempt {attempt+1} failed: {e}")
            if attempt == max_retries - 1:
                raise
            time.sleep(2 ** attempt)

    # 3. Возвращаем токен в зависимости от типа
    if file_type in ("video", "audio"):
        if token_from_api:
            return token_from_api
        else:
            try:
                result = resp.json()
                return result.get("token")
            except:
                return None
    else:
        try:
            result = resp.json()
            logger.error(f"CDN response JSON: {result}")

            token = None
            if "token" in result:
                token = result["token"]
            elif "photos" in result and isinstance(result["photos"], dict):
                for photo_key, photo_val in result["photos"].items():
                    if isinstance(photo_val, dict) and "token" in photo_val:
                        token = photo_val["token"]
                        break
            elif "photo_id" in result:
                token = result["photo_id"]
            else:
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
