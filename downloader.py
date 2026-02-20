import yt_dlp
import os
import tempfile
import requests
from typing import List, Dict, Optional, Tuple


class MediaDownloader:
    def __init__(self, temp_dir: Optional[str] = None):
        self.temp_dir = temp_dir or tempfile.mkdtemp()

    def extract_info(self, url: str) -> Dict:
        ydl_opts = {"quiet": True, "no_warnings": True}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            return ydl.extract_info(url, download=False)

    def download_best_video(self, url: str) -> Tuple[str, Dict]:
        # Пробуем форматы, которые не требуют ffmpeg
        # Сначала ищем готовый mp4
        # Затем любой другой готовый формат (кроме требующих слияния)
        # В крайнем случае используем лучший формат, но предупреждаем
        for fmt in ["best[ext=mp4]/best", "best"]:
            try:
                ydl_opts = {
                    "format": fmt,
                    "outtmpl": os.path.join(self.temp_dir, "%(title)s.%(ext)s"),
                    "quiet": True,
                    "no_warnings": True,
                }
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    info = ydl.extract_info(url, download=True)
                    filename = ydl.prepare_filename(info)
                    # Проверяем, что файл существует и не нулевой
                    if os.path.getsize(filename) > 0:
                        return filename, info
                    else:
                        raise Exception("Empty file")
            except Exception as e:
                continue  # пробуем следующий формат
        raise Exception("Не удалось скачать видео ни в одном формате")

    def download_thumbnail(self, url: str, info: Dict) -> Optional[str]:
        thumbnails = info.get("thumbnails", [])
        if not thumbnails:
            return None
        best = thumbnails[-1]
        thumb_url = best["url"]
        ext = thumb_url.split(".")[-1].split("?")[0]
        if ext not in ("jpg", "jpeg", "png", "webp"):
            ext = "jpg"
        thumb_path = os.path.join(self.temp_dir, f"thumbnail.{ext}")
        r = requests.get(thumb_url, stream=True)
        r.raise_for_status()
        with open(thumb_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        return thumb_path

    def download_all_images(self, url: str) -> List[str]:
        paths = []
        info = self.extract_info(url)
        if "entries" in info:
            for entry in info["entries"]:
                if entry.get("thumbnails"):
                    th_url = entry["thumbnails"][-1]["url"]
                    path = self._download_image(th_url, f"image_{entry['id']}.jpg")
                    if path:
                        paths.append(path)
        else:
            if info.get("url") and info.get("ext") in ("jpg", "png", "jpeg"):
                path = self._download_image(info["url"], f"image.{info['ext']}")
                if path:
                    paths.append(path)
        return paths

    def _download_image(self, url: str, filename: str) -> Optional[str]:
        path = os.path.join(self.temp_dir, filename)
        try:
            r = requests.get(url, stream=True, timeout=15)
            r.raise_for_status()
            with open(path, "wb") as f:
                for chunk in r.iter_content(8192):
                    f.write(chunk)
            return path
        except Exception:
            return None

    def get_description(self, info: Dict) -> Optional[str]:
        parts = []
        if info.get("title"):
            parts.append(info["title"])
        if info.get("description"):
            parts.append(info["description"])
        return "\n\n".join(parts) if parts else None

    def cleanup(self):
        import shutil
        shutil.rmtree(self.temp_dir, ignore_errors=True)
