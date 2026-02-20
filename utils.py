import tempfile
import shutil
from pathlib import Path


class TempDir:
    def __init__(self):
        self.path = Path(tempfile.mkdtemp())

    def cleanup(self):
        shutil.rmtree(self.path, ignore_errors=True)

    def __enter__(self):
        return self.path

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.cleanup()
