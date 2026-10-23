# Dithered radial lift for the dark stage: python tools/make_stage.py public/img/stage.png
# A dithered radial lift for the dark stage (CSS gradients band at 8 bits).
import sys
import numpy as np
from PIL import Image
W, H = 1080, 1920
out = sys.argv[1]
bg = np.array([0x0c, 0x0d, 0x10], float)
lift = np.array([0x1a, 0x1c, 0x22], float)
y, x = np.mgrid[0:H, 0:W].astype(float)
cx, cy = W * 0.5, H * 0.47
d = np.sqrt(((x - cx) / (W * 0.62)) ** 2 + ((y - cy) / (H * 0.42)) ** 2)
t = np.clip(1 - d, 0, 1) ** 1.6
img = bg[None, None, :] + (lift - bg)[None, None, :] * t[..., None]
rng = np.random.default_rng(7)
img = img + rng.uniform(-0.5, 0.5, img.shape) + rng.uniform(-0.5, 0.5, img.shape)
Image.fromarray(np.clip(np.round(img), 0, 255).astype(np.uint8)).save(out)
