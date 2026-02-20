import yadisk
import os
from typing import Optional
from config import YANDEX_DISK_TOKEN


class YandexDiskUploader:
    def __init__(self, token: str):
        self.y = yadisk.YaDisk(token=token)
        if not self.y.check_token():
            raise ValueError("Invalid Yandex Disk token")

    def upload_file(self, file_path: str, remote_path: str = "/bots_temp/") -> Optional[str]:
        filename = os.path.basename(file_path)
        remote_full = os.path.join(remote_path, filename).replace("\\", "/")
        try:
            self.y.mkdir(remote_path)
        except:
            pass
        self.y.upload(file_path, remote_full, overwrite=True)
        self.y.publish(remote_full)
        info = self.y.get_meta(remote_full)
        return info.public_url
