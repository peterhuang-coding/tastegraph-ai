"""CLIP embedding service for visual scoring.

Computes image and text embeddings using OpenAI CLIP, stores them
in a simple JSON file keyed by image_id, and provides similarity
scoring against taste concepts and themes.
"""

import json
import hashlib
from pathlib import Path
from typing import Optional

import clip
import numpy as np
import torch
import torch.nn.functional as F
from PIL import Image

from taste_graph_ai.config import CLIP_MODEL_NAME, CLIP_DEVICE, DATA_DIR

EMBEDDINGS_FILE = DATA_DIR / "clip_embeddings.json"


class CLIPService:
    """Lazy-loaded CLIP model for embedding and similarity scoring."""

    def __init__(self, model_name: str = None, device: str = None):
        self._model_name = model_name or CLIP_MODEL_NAME
        self._device = device or CLIP_DEVICE
        self._model = None
        self._preprocess = None
        self._embeddings: dict[str, list[float]] = {}
        self._loaded = False

    @property
    def model(self):
        if self._model is None:
            self._model, self._preprocess = clip.load(self._model_name, device=self._device)
            self._model.eval()
        return self._model

    @property
    def preprocess(self):
        if self._preprocess is None:
            _ = self.model  # triggers load
        return self._preprocess

    # ── Embedding ────────────────────────────────────────────

    def embed_image(self, image_path: str | Path) -> Optional[list[float]]:
        """Compute CLIP embedding for an image file."""
        path = Path(image_path)
        if not path.exists():
            return None

        # Use file hash as cache key
        cache_key = self._cache_key(str(path))
        if cache_key in self._embeddings:
            return self._embeddings[cache_key]

        try:
            img = self.preprocess(Image.open(path)).unsqueeze(0).to(self._device)
            with torch.no_grad():
                features = self.model.encode_image(img)
                features = F.normalize(features, dim=-1)
            emb = features.cpu().numpy().flatten().tolist()
            self._embeddings[cache_key] = emb
            return emb
        except Exception:
            return None

    def embed_text(self, text: str) -> Optional[list[float]]:
        """Compute CLIP embedding for a text string."""
        if not text:
            return None
        try:
            tokens = clip.tokenize([text], truncate=True).to(self._device)
            with torch.no_grad():
                features = self.model.encode_text(tokens)
                features = F.normalize(features, dim=-1)
            return features.cpu().numpy().flatten().tolist()
        except Exception:
            return None

    def compute_similarity(
        self, image_path: str | Path, text: str
    ) -> float:
        """Cosine similarity between image and text embeddings. Range [0, 1] after normalization shift."""
        img_emb = self.embed_image(image_path)
        text_emb = self.embed_text(text)
        if img_emb is None or text_emb is None:
            return 0.5  # Neutral score

        img_vec = np.array(img_emb)
        text_vec = np.array(text_emb)
        sim = float(np.dot(img_vec, text_vec))
        # CLIP cosine similarity is roughly [-0.2, 0.5] in practice;
        # map to [0, 1] range for scoring
        return max(0.0, min(1.0, (sim + 0.2) / 0.7))

    def batch_similarity(
        self, image_paths: list[str | Path], text: str
    ) -> list[float]:
        """Compute similarity for multiple images against a single text prompt."""
        text_emb = self.embed_text(text)
        if text_emb is None:
            return [0.5] * len(image_paths)
        text_vec = np.array(text_emb)

        scores = []
        for p in image_paths:
            img_emb = self.embed_image(p)
            if img_emb is None:
                scores.append(0.5)
            else:
                sim = float(np.dot(np.array(img_emb), text_vec))
                scores.append(max(0.0, min(1.0, (sim + 0.2) / 0.7)))
        return scores

    # ── Persistence ──────────────────────────────────────────

    def _cache_key(self, path_or_text: str) -> str:
        return hashlib.md5(path_or_text.encode()).hexdigest()[:16]

    def save(self, path: Optional[Path] = None) -> Path:
        target = path or EMBEDDINGS_FILE
        target.write_text(json.dumps(self._embeddings, ensure_ascii=False))
        return target

    def load(self, path: Optional[Path] = None) -> "CLIPService":
        target = path or EMBEDDINGS_FILE
        if target.exists():
            try:
                self._embeddings = json.loads(target.read_text())
            except (json.JSONDecodeError, IOError):
                self._embeddings = {}
        self._loaded = True
        return self


# ── Singleton ────────────────────────────────────────────────

_clip_service: Optional[CLIPService] = None


def get_clip() -> CLIPService:
    global _clip_service
    if _clip_service is None:
        _clip_service = CLIPService().load()
    return _clip_service
