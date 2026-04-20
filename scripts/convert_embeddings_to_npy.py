"""Convert embeddings_cache.json to numpy binary format.

Reduces memory footprint from ~3.8GB (Python float objects) to ~167MB
(contiguous float32 array) for the same 28K×1536 embedding matrix.

Usage:
    python scripts/convert_embeddings_to_npy.py [--kb-dir processed_knowledge_base]
"""

import argparse
import json
import sys
from pathlib import Path

import numpy as np


def convert(kb_dir: Path) -> None:
    json_path = kb_dir / "embeddings_cache.json"
    npy_path = kb_dir / "embeddings_cache.npy"
    meta_path = kb_dir / "embeddings_cache_meta.json"

    if not json_path.exists():
        print(f"No JSON cache at {json_path}, skipping conversion.")
        sys.exit(0)

    if npy_path.exists():
        print(f"Numpy cache already exists at {npy_path}, skipping.")
        sys.exit(0)

    print(f"Loading {json_path} ...")
    with json_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    embeddings = data.get("embeddings")
    if not embeddings:
        print("No embeddings found in cache, skipping.")
        sys.exit(1)

    arr = np.array(embeddings, dtype=np.float32)
    print(f"Converted {arr.shape[0]} embeddings × {arr.shape[1]} dims to float32")
    print(f"  JSON size:  {json_path.stat().st_size / (1024**2):.1f} MB")

    np.save(npy_path, arr)
    print(f"  Numpy size: {npy_path.stat().st_size / (1024**2):.1f} MB")

    meta = {
        "cache_key": data.get("cache_key"),
        "model": data.get("model"),
        "chunks": data.get("chunks"),
        "chunk_index": data.get("chunk_index"),
    }
    with meta_path.open("w", encoding="utf-8") as f:
        json.dump(meta, f)

    print(f"Saved metadata to {meta_path}")
    print("Conversion complete. You can now remove the JSON cache to save disk space.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Convert embeddings JSON to numpy format")
    parser.add_argument("--kb-dir", default="processed_knowledge_base", type=Path)
    args = parser.parse_args()
    convert(args.kb_dir)
