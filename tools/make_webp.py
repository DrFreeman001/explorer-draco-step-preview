"""Assemble des images PNG numérotées en WebP animé (Pillow nécessaire, pas dans le projet).

Usage : python tools/make_webp.py <dossier d'images> <sortie.webp> [--fps 16] [--quality 82]
"""
import argparse
from pathlib import Path

from PIL import Image

parser = argparse.ArgumentParser()
parser.add_argument("frames", type=Path)
parser.add_argument("out", type=Path)
parser.add_argument("--fps", type=int, default=16)
parser.add_argument("--quality", type=int, default=82)
args = parser.parse_args()
images = [Image.open(p).convert("RGB") for p in sorted(args.frames.glob("*.png"))]
images[0].save(args.out, save_all=True, append_images=images[1:], duration=round(1000 / args.fps), loop=0,
               quality=args.quality, method=6)
print(args.out, len(images), "images", args.out.stat().st_size // 1024, "Ko")
