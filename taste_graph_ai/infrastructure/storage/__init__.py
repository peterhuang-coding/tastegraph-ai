from pathlib import Path
from shutil import copyfile
from urllib.parse import urlparse

from taste_graph_ai.config import IMAGES_DIR


class FileStore:
    """Local file storage for images."""

    def __init__(self, base_dir: Path = IMAGES_DIR):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, source_path: Path, file_id: str) -> Path:
        ext = source_path.suffix or ".jpg"
        dest = self.base_dir / f"{file_id}{ext}"
        copyfile(source_path, dest)
        return dest

    def save_bytes(self, data: bytes, file_id: str, ext: str = ".jpg") -> Path:
        dest = self.base_dir / f"{file_id}{ext}"
        dest.write_bytes(data)
        return dest

    def get_path(self, file_id: str) -> Path:
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            p = self.base_dir / f"{file_id}{ext}"
            if p.exists():
                return p
        return self.base_dir / f"{file_id}.jpg"

    def exists(self, file_id: str) -> bool:
        for ext in (".jpg", ".jpeg", ".png", ".webp"):
            if (self.base_dir / f"{file_id}{ext}").exists():
                return True
        return False

    def delete(self, file_id: str) -> None:
        path = self.get_path(file_id)
        if path.exists():
            path.unlink()
