import yt_dlp
import os
import tempfile
import requests
import json
import logging
from typing import List, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

class MediaDownloader:
    def __init__(self, temp_dir: Optional[str] = None):
        self.temp_dir = temp_dir or tempfile.mkdtemp()

    def extract_info(self, url: str) -> Dict:
        ydl_opts = {"quiet": True, "no_warnings": True, "cookiefile": "cookies.txt"}
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            # Логируем структуру (только ключи, чтобы не засорять)
            logger.error(f"Extracted info keys for {url}: {list(info.keys())}")
            # Если есть 'entries' (плейлист/карусель), логируем количество
            if 'entries' in info:
                logger.error(f"Number of entries: {len(info['entries'])}")
            return info

    def download_best_video(self, url: str) -> Tuple[str, Dict]:
        """
        Скачивает видео в наилучшем доступном качестве,
        объединяет видео и аудио в один MP4-файл.
        """
        ydl_opts = {
            'format': 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
            'outtmpl': os.path.join(self.temp_dir, '%(title)s.%(ext)s'),
            'quiet': True,
            'no_warnings': True,
            'cookiefile': 'cookies.txt',
            'merge_output_format': 'mp4',
            'postprocessors': [{
                'key': 'FFmpegVideoConvertor',
                'preferedformat': 'mp4',
            }],
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                # После слияния расширение может стать .mp4
                if not os.path.exists(filename):
                    base = os.path.splitext(filename)[0]
                    if os.path.exists(base + '.mp4'):
                        filename = base + '.mp4'
                return filename, info
        except Exception as e:
            logger.error(f"Failed to download best video: {e}")
            raise

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
        except Exception as e:
            logger.error(f"Failed to download image {url}: {e}")
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
