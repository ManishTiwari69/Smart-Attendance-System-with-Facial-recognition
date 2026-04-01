"""
backend/services/face_recognition.py
─────────────────────────────────────────────────────────────────────────────
Face recognition pipeline using MTCNN (face detection) + FaceNet
(InceptionResnetV1, embedding extraction).

Flow:
    Enrolment  → detect face → align crop → extract 512-d embedding → store in DB
    Verification → same pipeline → cosine similarity vs stored embeddings → pass/fail

Key design decisions:
    • Multiple embeddings per user (up to MAX_FACE_ENROLLMENT_IMAGES).
      Verification uses the mean embedding to improve robustness.
    • Liveness detection stub: blink / challenge-response hooks for production upgrade.
    • Thread-safe: models loaded once at module level, shared across requests.
    • Works with PIL Images or raw base64-encoded JPEG/PNG strings (from browser webcam).
"""

from __future__ import annotations

import base64
import io
import logging
import os
from dataclasses import dataclass
from typing import Optional

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)

# ─── Lazy Model Loading ───────────────────────────────────────────────────────
# Models are large; import at module level but initialise only on first use.

_mtcnn   = None   # facenet_pytorch.MTCNN
_facenet = None   # facenet_pytorch.InceptionResnetV1


def _load_models():
    """Load MTCNN and FaceNet models (once, on first call)."""
    global _mtcnn, _facenet

    if _mtcnn is not None:
        return  # already loaded

    # Import here so the module can be imported even if torch isn't installed
    # (e.g. during schema migrations)
    try:
        import torch
        from facenet_pytorch import MTCNN, InceptionResnetV1

        device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
        logger.info(f"[FaceNet] Loading models on device: {device}")

        _mtcnn = MTCNN(
            image_size=int(os.getenv("MTCNN_IMAGE_SIZE", 160)),
            margin=20,
            min_face_size=int(os.getenv("MTCNN_MIN_FACE_SIZE", 40)),
            thresholds=[float(t) for t in
                        os.getenv("MTCNN_THRESHOLDS", "0.6,0.7,0.7").split(",")],
            keep_all=False,      # return only the largest / most confident face
            device=device,
            post_process=True,   # normalise to [-1, 1] range for FaceNet
        )

        _facenet = InceptionResnetV1(
            pretrained="vggface2",   # best general-purpose weights
            classify=False,          # embedding mode (not classification)
        ).eval().to(device)

        logger.info("[FaceNet] Models loaded successfully.")

    except ImportError as exc:
        logger.error(
            f"[FaceNet] facenet-pytorch not installed: {exc}. "
            "Install with: pip install facenet-pytorch"
        )
        raise


# ─── Data Classes ─────────────────────────────────────────────────────────────

@dataclass
class DetectionResult:
    """Result of MTCNN face detection on a single image."""
    detected:       bool
    face_crop:      Optional[Image.Image]   # 160×160 aligned face
    probability:    float                   # MTCNN confidence (0–1)
    bounding_box:   Optional[list]          # [x1, y1, x2, y2]
    embedding:      Optional[np.ndarray]    # 512-d float32, if facenet ran


@dataclass
class VerificationResult:
    """Output of a face verification attempt."""
    verified:       bool
    similarity:     float    # cosine similarity (0–1, higher = more similar)
    threshold:      float    # the threshold used
    num_comparisons: int     # how many stored embeddings were compared
    message:        str


# ─── Core Functions ───────────────────────────────────────────────────────────

def decode_image(data: str | bytes) -> Image.Image:
    """
    Accept:
        - base64 data URL:  "data:image/jpeg;base64,/9j/4AAQ..."
        - raw base64 bytes: b"/9j/4AAQ..."
        - PIL Image passthrough
    Returns a PIL RGB Image.
    """
    if isinstance(data, Image.Image):
        return data.convert("RGB")

    if isinstance(data, str):
        if data.startswith("data:"):
            # strip "data:image/jpeg;base64," prefix
            data = data.split(",", 1)[1]
        raw = base64.b64decode(data)
    else:
        raw = base64.b64decode(data) if not isinstance(data, (bytes, bytearray)) else data

    return Image.open(io.BytesIO(raw)).convert("RGB")


def detect_and_embed(image_data: str | bytes | Image.Image) -> DetectionResult:
    """
    Run MTCNN detection + FaceNet embedding extraction on a single image.

    Args:
        image_data: Base64 string (data URL or raw), raw bytes, or PIL Image.

    Returns:
        DetectionResult with embedding populated on success.
    """
    _load_models()

    import torch

    try:
        img_pil = decode_image(image_data)
    except Exception as exc:
        logger.warning(f"[FaceNet] Could not decode image: {exc}")
        return DetectionResult(False, None, 0.0, None, None)

    # ── Step 1: MTCNN – detect and align face ──────────────────────────────
    try:
        face_tensor, prob = _mtcnn(img_pil, return_prob=True)
    except Exception as exc:
        logger.warning(f"[FaceNet] MTCNN error: {exc}")
        return DetectionResult(False, None, 0.0, None, None)

    if face_tensor is None or prob is None:
        return DetectionResult(False, None, 0.0, None, None)

    probability = float(prob)

    # Reconstruct a PIL crop for storage / display
    # face_tensor is (3, 160, 160), values in [-1,1] post-processed
    # Reverse normalisation for PIL: (x + 1) / 2 * 255
    face_np = ((face_tensor.permute(1, 2, 0).numpy() + 1) / 2 * 255).astype(np.uint8)
    face_crop = Image.fromarray(face_np)

    # Bounding box (for display overlay in frontend)
    try:
        boxes, _ = _mtcnn.detect(img_pil)
        bbox = boxes[0].tolist() if boxes is not None else None
    except Exception:
        bbox = None

    # ── Step 2: FaceNet – extract 512-d embedding ──────────────────────────
    try:
        batch = face_tensor.unsqueeze(0)   # (1, 3, 160, 160)
        with torch.no_grad():
            embedding = _facenet(batch).squeeze(0).cpu().numpy()  # (512,)
        # L2-normalise so cosine similarity == dot product
        embedding = embedding / (np.linalg.norm(embedding) + 1e-10)
    except Exception as exc:
        logger.error(f"[FaceNet] Embedding extraction failed: {exc}")
        return DetectionResult(True, face_crop, probability, bbox, None)

    return DetectionResult(
        detected=True,
        face_crop=face_crop,
        probability=probability,
        bounding_box=bbox,
        embedding=embedding,
    )


def embedding_to_bytes(embedding: np.ndarray) -> bytes:
    """Serialise float32 embedding array to bytes for DB storage."""
    return embedding.astype(np.float32).tobytes()


def bytes_to_embedding(raw: bytes) -> np.ndarray:
    """Deserialise bytes from DB back to float32 numpy array."""
    return np.frombuffer(raw, dtype=np.float32).copy()


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """
    Cosine similarity between two L2-normalised vectors.
    Range: [-1, 1]. Identical vectors → 1.0.
    """
    return float(np.dot(a, b))


def verify_face(
    query_image: str | bytes | Image.Image,
    stored_embeddings: list[bytes],
    threshold: Optional[float] = None,
) -> VerificationResult:
    """
    Verify a query face image against a list of stored embeddings.

    Strategy: compute cosine similarity between the query embedding and the
    MEAN of all stored embeddings (averaging improves accuracy across varied
    enrolment images).

    Args:
        query_image:        Webcam capture (base64, bytes, or PIL).
        stored_embeddings:  List of raw embedding bytes from FaceEmbedding.embedding_bytes.
        threshold:          Override the env-configured threshold.

    Returns:
        VerificationResult
    """
    if not stored_embeddings:
        return VerificationResult(
            verified=False, similarity=0.0,
            threshold=threshold or 0.75,
            num_comparisons=0,
            message="No face enrolled for this user.",
        )

    threshold = threshold or float(os.getenv("FACE_EMBEDDING_THRESHOLD", 0.75))

    # Detect + embed query face
    result = detect_and_embed(query_image)
    if not result.detected or result.embedding is None:
        return VerificationResult(
            verified=False, similarity=0.0,
            threshold=threshold,
            num_comparisons=len(stored_embeddings),
            message="No face detected in query image.",
        )

    query_emb = result.embedding

    # Reconstruct stored embeddings
    stored_embs = []
    for raw in stored_embeddings:
        try:
            stored_embs.append(bytes_to_embedding(raw))
        except Exception:
            continue

    if not stored_embs:
        return VerificationResult(
            verified=False, similarity=0.0,
            threshold=threshold,
            num_comparisons=0,
            message="Stored embeddings could not be deserialised.",
        )

    # Compare against mean embedding
    mean_emb = np.mean(stored_embs, axis=0)
    mean_emb = mean_emb / (np.linalg.norm(mean_emb) + 1e-10)   # re-normalise

    similarity = cosine_similarity(query_emb, mean_emb)
    verified = similarity >= threshold

    logger.info(
        f"[FaceVerify] similarity={similarity:.4f} threshold={threshold} "
        f"→ {'PASS' if verified else 'FAIL'}"
    )

    return VerificationResult(
        verified=verified,
        similarity=round(similarity, 6),
        threshold=threshold,
        num_comparisons=len(stored_embs),
        message="Verification successful." if verified else
                f"Similarity {similarity:.2f} below threshold {threshold}.",
    )


def enroll_faces(
    images: list[str | bytes | Image.Image],
    quality_threshold: float = 0.95,
) -> tuple[list[bytes], list[float], list[str]]:
    """
    Process a batch of face images for enrolment.

    Args:
        images:             List of images (base64/bytes/PIL).
        quality_threshold:  Reject faces with MTCNN confidence below this.

    Returns:
        (embedding_bytes_list, quality_scores, warnings)
        embedding_bytes_list: list of bytes ready for FaceEmbedding.embedding_bytes
        quality_scores:       MTCNN probabilities per accepted image
        warnings:             Human-readable rejection reasons
    """
    embedding_bytes_list = []
    quality_scores = []
    warnings = []

    for i, img_data in enumerate(images):
        result = detect_and_embed(img_data)

        if not result.detected:
            warnings.append(f"Image {i+1}: No face detected.")
            continue

        if result.probability < quality_threshold:
            warnings.append(
                f"Image {i+1}: Low quality ({result.probability:.2f} < {quality_threshold}). "
                "Please use better lighting or angle."
            )
            continue

        if result.embedding is None:
            warnings.append(f"Image {i+1}: Embedding extraction failed.")
            continue

        embedding_bytes_list.append(embedding_to_bytes(result.embedding))
        quality_scores.append(result.probability)

    return embedding_bytes_list, quality_scores, warnings


# ─── Liveness Detection Stub ──────────────────────────────────────────────────

class LivenessChallenge:
    """
    Stub for liveness detection to prevent photo/video spoofing.
    In production, integrate:
        • Blink detection (OpenCV dlib landmarks)
        • Head-pose challenge (turn left/right)
        • Depth sensor (if hardware available)
        • Anti-spoofing model (e.g. Silent-Face Anti-Spoofing)
    """

    CHALLENGES = ["blink", "turn_left", "turn_right", "smile", "nod"]

    def __init__(self):
        import random
        self.challenge = random.choice(self.CHALLENGES)
        self.passed = False

    def verify_response(self, frames: list[Image.Image]) -> bool:
        """
        TODO: Implement per-challenge verification.
        Currently always returns True (demo mode).
        """
        logger.warning("[Liveness] Liveness check is in DEMO mode – always passes.")
        self.passed = True
        return True

    def to_dict(self):
        return {"challenge": self.challenge, "passed": self.passed}


# ─── Utility: Save face crop to disk (for audit / retraining) ────────────────

def save_face_crop(
    face_crop: Image.Image,
    user_id: str,
    label: str = "enroll",
) -> str | None:
    """
    Save an aligned face crop to FACE_STORE_PATH/{user_id}/{label}_{timestamp}.jpg.
    Returns the saved path, or None on failure.
    """
    store_path = os.getenv("FACE_STORE_PATH", "./face_store")
    try:
        user_dir = os.path.join(store_path, str(user_id))
        os.makedirs(user_dir, exist_ok=True)
        from datetime import datetime
        filename = f"{label}_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')}.jpg"
        filepath = os.path.join(user_dir, filename)
        face_crop.save(filepath, "JPEG", quality=95)
        return filepath
    except Exception as exc:
        logger.error(f"[FaceStore] Failed to save face crop: {exc}")
        return None
