import hashlib
import re
import numpy as np


def _extract_features(text: str) -> list[str]:
    clean = re.sub(r"[^a-z0-9áàâãéèêíïóôõöúçñ\s-]", " ", text.lower())
    tokens = [t for t in clean.split() if len(t) >= 2]
    features = list(tokens)
    for token in tokens:
        padded = f"<{token}>"
        for n in (3, 4, 5):
            if len(padded) >= n:
                features.extend(padded[i : i + n] for i in range(len(padded) - n + 1))
    return features


def generate_embedding(text: str, dim: int = 384) -> list[float]:
    vec = np.zeros(dim, dtype=np.float32)
    for feat in _extract_features(text):
        digest = hashlib.blake2b(feat.encode("utf-8"), digest_size=8).digest()
        h = int.from_bytes(digest, "little")
        idx = h % dim
        sign = 1.0 if (h >> 63) == 0 else -1.0
        vec[idx] += sign

    norm = np.linalg.norm(vec)
    return (vec / norm).tolist() if norm > 0 else vec.tolist()
