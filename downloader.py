import yt_dlp
import os
import tempfile
import requests
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
            logger.info(f"Extracted info keys for {url}: {list(info.keys())}")
            if 'entries' in info:
                logger.info(f"Number of entries: {len(info['entries'])}")
            return info

    def download_best_video(self, url: str, extractor_key: str = None) -> Tuple[str, Dict]:
        """
        Скачивает видео с учётом источника.
        Для YouTube пытается получить H.264, для остальных пробует разные стратегии.
        """
        strategies = []
        if extractor_key == 'Youtube':
            strategies = [
                {'format': 'bestvideo[ext=mp4][vcodec^=avc1]+bestaudio[ext=m4a]/best[ext=mp4][vcodec^=avc1]'},
                {'format': 'best[ext=mp4]'},
                {'format': 'best'},
            ]
        else:
            # Для Instagram, Pinterest и других – сначала лучший mp4, потом любой
            strategies = [
                {'format': 'best[ext=mp4]'},
                {'format': 'best'},
            ]

        last_error = None
        for strat in strategies:
            try:
                ydl_opts = {
                    'format': strat['format'],
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
                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                    logger.info(f"Trying format: {strat['format']} for {extractor_key}")
                    info = ydl.extract_info(url, download=True)
                    filename = ydl.prepare_filename(info)
                    if not os.path.exists(filename):
                        base = os.path.splitext(filename)[0]
                        if os.path.exists(base + '.mp4'):
                            filename = base + '.mp4'
                    return filename, info
            except Exception as e:
                logger.warning(f"Strategy {strat} failed: {e}")
                last_error = e
                continue
        raise last_error or Exception("Failed to download video")

    def download_media(self, url: str, info: Dict) -> List[Tuple[str, str]]:
        """
        Универсальный метод: для каждой записи определяет тип и скачивает.
        При ошибке скачивания видео пробует скачать изображение.
        """
        result = []
        entries = info.get('entries')
        if entries and isinstance(entries, list):
            logger.info(f"Processing playlist with {len(entries)} entries")
            for idx, entry in enumerate(entries):
                if not entry:
                    continue
                logger.info(f"Entry {idx+1} keys: {list(entry.keys())}")

                # Определяем, является ли элемент видео
                is_video = False
                # Проверяем наличие длительности (часто признак видео)
                if entry.get('duration'):
                    is_video = True
                    logger.info(f"Entry {idx+1} has duration -> considered video")
                # Проверяем наличие видеокодека
                elif entry.get('vcodec') and entry['vcodec'] != 'none':
                    is_video = True
                    logger.info(f"Entry {idx+1} has vcodec -> considered video")
                # Проверяем расширение
                elif entry.get('ext') in ('mp4', 'mov', 'webm', 'm4a'):
                    is_video = True
                    logger.info(f"Entry {idx+1} has video extension -> considered video")
                # Проверяем форматы
                elif entry.get('formats'):
                    for f in entry['formats']:
                        if f.get('vcodec') and f['vcodec'] != 'none':
                            is_video = True
                            logger.info(f"Entry {idx+1} has formats with video -> considered video")
                            break

                video_downloaded = False
                if is_video:
                    try:
                        video_url = entry.get('webpage_url') or entry.get('url') or url
                        extractor = entry.get('extractor_key')
                        logger.info(f"Attempting to download video from entry {idx+1}, extractor: {extractor}")
                        video_file, _ = self.download_best_video(video_url, extractor_key=extractor)
                        if video_file and os.path.exists(video_file):
                            result.append(("video", video_file))
                            video_downloaded = True
                            logger.info(f"Video from entry {idx+1} downloaded")
                    except Exception as e:
                        logger.warning(f"Video download failed for entry {idx+1}: {e}")

                # Если видео не скачалось (или не было видео), пробуем изображение
                if not video_downloaded:
                    logger.info(f"Attempting to download image from entry {idx+1}")
                    img_url = None
                    if entry.get('url') and entry.get('ext') in ('jpg', 'png', 'jpeg', 'webp'):
                        img_url = entry['url']
                        logger.info(f"Image URL from direct url: {img_url}")
                    elif entry.get('thumbnails'):
                        img_url = entry['thumbnails'][-1]['url']
                        logger.info(f"Image URL from thumbnails: {img_url}")
                    elif entry.get('thumbnail'):
                        img_url = entry['thumbnail']
                        logger.info(f"Image URL from thumbnail: {img_url}")
                    elif entry.get('display_url'):
                        img_url = entry['display_url']
                        logger.info(f"Image URL from display_url: {img_url}")
                    elif entry.get('image_url'):
                        img_url = entry['image_url']
                        logger.info(f"Image URL from image_url: {img_url}")

                    if img_url:
                        img_path = self._download_image(img_url, f"image_{entry.get('id', '')}.jpg")
                        if img_path and os.path.exists(img_path):
                            result.append(("image", img_path))
                            logger.info(f"Image from entry {idx+1} downloaded")
                        else:
                            logger.error(f"Failed to download image for entry {idx+1}")
                    else:
                        logger.warning(f"No image URL found for entry {idx+1}")

        else:
            # Одиночный пост
            logger.info("Single post processing")
            logger.info(f"Info keys: {list(info.keys())}")

            is_video = False
            if info.get('duration'):
                is_video = True
                logger.info("Has duration -> considered video")
            elif info.get('vcodec') and info['vcodec'] != 'none':
                is_video = True
                logger.info("Has vcodec -> considered video")
            elif info.get('ext') in ('mp4', 'mov', 'webm', 'm4a'):
                is_video = True
                logger.info("Has video extension -> considered video")
            elif info.get('formats'):
                for f in info['formats']:
                    if f.get('vcodec') and f['vcodec'] != 'none':
                        is_video = True
                        logger.info("Has formats with video -> considered video")
                        break

            video_downloaded = False
            if is_video:
                try:
                    extractor = info.get('extractor_key')
                    logger.info(f"Attempting to download video, extractor: {extractor}")
                    video_file, _ = self.download_best_video(url, extractor_key=extractor)
                    if video_file and os.path.exists(video_file):
                        result.append(("video", video_file))
                        video_downloaded = True
                        logger.info("Video downloaded")
                except Exception as e:
                    logger.warning(f"Video download failed: {e}")

            if not video_downloaded:
                logger.info("Attempting to download image")
                img_url = None
                if info.get('url') and info.get('ext') in ('jpg', 'png', 'jpeg', 'webp'):
                    img_url = info['url']
                    logger.info(f"Image URL from direct url: {img_url}")
                elif info.get('thumbnails'):
                    img_url = info['thumbnails'][-1]['url']
                    logger.info(f"Image URL from thumbnails: {img_url}")
                elif info.get('thumbnail'):
                    img_url = info['thumbnail']
                    logger.info(f"Image URL from thumbnail: {img_url}")
                elif info.get('display_url'):
                    img_url = info['display_url']
                    logger.info(f"Image URL from display_url: {img_url}")
                elif info.get('image_url'):
                    img_url = info['image_url']
                    logger.info(f"Image URL from image_url: {img_url}")

                if img_url:
                    img_path = self._download_image(img_url, f"image.{info.get('ext', 'jpg')}")
                    if img_path and os.path.exists(img_path):
                        result.append(("image", img_path))
                        logger.info("Image downloaded")
                    else:
                        logger.error("Failed to download image")
                else:
                    logger.warning("No image URL found")

        return result

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
