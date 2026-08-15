"""Has the screen meaningfully changed since the last glance?

The vision loop's whole cost is the VLM: ~35s at ~96% GPU per analysed
frame, on a 300s interval. Skipping a glance when nothing happened is worth
more than any other optimisation available here, so the skip test has to
actually fire.

The previous test was `f"{len(b64)}-{b64[:100]}-{b64[-100:]}"` over the
JPEG bytes. Measured against real captures:

  * it skipped 0 of 9 consecutive live captures;
  * it failed to skip even a SINGLE CHANGED PIXEL;
  * `b64[:100]` was byte-identical across every capture — it is the JPEG
    header at fixed quality and dimensions, so a third of the hash carried
    no screen information whatsoever.

Byte equality is the wrong question: at JPEG quality 70 a clock digit or a
blinking cursor rewrites the entropy-coded tail. A difference hash asks the
question we actually mean — is this the same screen, roughly — and on the
same captures scored 0 for one pixel, 1 for a clock's worth of digits, and
57 for half the screen replaced.
"""
import base64
import logging
from io import BytesIO
from typing import Optional

import numpy as np
from PIL import Image

log = logging.getLogger(__name__)

# Resized to (HASH_SIZE+1) wide by HASH_SIZE tall, then each pixel is
# compared to its right neighbour → HASH_SIZE * HASH_SIZE bits. Big enough
# that a window swap moves dozens of bits, small enough that font
# antialiasing moves none.
HASH_SIZE = 16
HASH_BITS = HASH_SIZE * HASH_SIZE


def dhash(img_b64: str) -> Optional[np.ndarray]:
    """Difference hash of a base64 image: greyscale, downsample, then compare
    each pixel to its right-hand neighbour. Returns a bool array of
    HASH_BITS, or None if the image could not be decoded.

    Comparing neighbours rather than absolute levels is what makes this
    immune to a global brightness or gamma shift.
    """
    try:
        img = Image.open(BytesIO(base64.b64decode(img_b64))).convert("L")
        small = np.asarray(
            img.resize((HASH_SIZE + 1, HASH_SIZE), Image.Resampling.LANCZOS),
            dtype=np.int16,
        )
        return (small[:, 1:] > small[:, :-1]).flatten()
    except Exception as e:
        log.debug(f"dhash failed: {e}")
        return None


def distance(a: Optional[np.ndarray], b: Optional[np.ndarray]) -> int:
    """Hamming distance in bits. An un-hashable frame is treated as maximally
    different, so a decode failure analyses the frame rather than silently
    dropping it — the loop's job is to look, and the expensive mistake is
    not looking."""
    if a is None or b is None or a.shape != b.shape:
        return HASH_BITS
    return int(np.count_nonzero(a != b))
