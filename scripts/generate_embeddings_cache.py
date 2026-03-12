"""Generate the pre-committed embeddings cache for instant first boot.

Usage:
    .venv/bin/python scripts/generate_embeddings_cache.py
    .venv/bin/python scripts/generate_embeddings_cache.py --incremental

The --incremental flag loads the existing cache and only generates embeddings
for new or modified chunks, making updates after small KB changes fast.

Requires OPENAI_API_KEY to be set. Loads the KB, generates embeddings via
OpenAI, and writes the cache to processed_knowledge_base/embeddings_cache.json.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import config
from backend.core.loader import KnowledgeBase


# text-embedding-3-small has an 8191-token limit per text.
# Legislative text tokenises at roughly 1.4–2 chars/token, so we cap at
# 10,000 chars (~5,000–7,000 tokens) to stay safely within the limit.
_MAX_EMBED_CHARS = 10_000


def _chunk_index_text(chunk) -> str:
    if chunk.header:
        text = f"{chunk.header}\n{chunk.chunk_text}"
    else:
        text = chunk.chunk_text
    if len(text) > _MAX_EMBED_CHARS:
        text = text[:_MAX_EMBED_CHARS]
    return text


def _text_hash(text: str) -> str:
    """Short hash of chunk text for change detection."""
    return hashlib.sha256(text.encode()).hexdigest()[:12]


def _cache_key(texts: list[str], model: str) -> str:
    hasher = hashlib.sha256()
    hasher.update(model.encode())
    for text in texts:
        hasher.update(text.encode())
    return hasher.hexdigest()[:16]


def _load_existing_chunk_index(cache_path: Path) -> dict | None:
    """Load existing cache and return chunk-level index if available."""
    if not cache_path.exists():
        return None
    try:
        with cache_path.open("r", encoding="utf-8") as f:
            data = json.load(f)

        # New format has chunk_index for incremental updates
        if "chunk_index" in data:
            return data["chunk_index"]

        # Old format: positional list — can't reuse without chunk keys
        print("  Existing cache is old format (positional). Full rebuild needed.")
        return None
    except Exception:
        return None


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate embeddings cache")
    parser.add_argument("--incremental", action="store_true",
                        help="Only generate embeddings for new/changed chunks")
    args = parser.parse_args()

    if not config.embeddings_configured():
        print("ERROR: OPENAI_API_KEY not set. Cannot generate embeddings.")
        sys.exit(1)

    print(f"Loading knowledge base from {config.KB_DIR} ...")
    kb = KnowledgeBase()
    kb.load(config.KB_DIR)
    print(f"Loaded {len(kb.chunks)} chunks")

    if not kb.chunks:
        print("ERROR: No chunks loaded. Check KB_DIR.")
        sys.exit(1)

    texts = [_chunk_index_text(c) for c in kb.chunks]
    key = _cache_key(texts, config.EMBEDDINGS_MODEL)
    output_path = Path(config.KB_DIR) / "embeddings_cache.json"

    # Build chunk-level keys: "chunk_id:text_hash" for incremental comparison
    chunk_keys = []
    for chunk, text in zip(kb.chunks, texts):
        ck = f"{chunk.chunk_id}:{_text_hash(text)}"
        chunk_keys.append(ck)

    # Incremental mode: load existing cache and reuse unchanged embeddings
    existing_index = None
    reused_count = 0
    if args.incremental:
        print("Incremental mode: checking existing cache ...")
        existing_index = _load_existing_chunk_index(output_path)
        if existing_index:
            reused_count = sum(1 for ck in chunk_keys if ck in existing_index)
            new_count = len(chunk_keys) - reused_count
            print(f"  {reused_count} chunks unchanged (reusing embeddings)")
            print(f"  {new_count} chunks new/modified (need embedding)")

            if new_count == 0:
                print("Nothing to do — cache is up to date.")
                return
        else:
            print("  No reusable cache found. Full rebuild.")

    print(f"Generating embeddings with {config.EMBEDDINGS_MODEL} ...")
    print(f"Cache key: {key}")

    from openai import OpenAI
    client = OpenAI()

    MAX_BATCH_CHARS = 14_000

    # Build the chunk index: chunk_key → embedding vector
    chunk_index: dict[str, list[float]] = {}

    # Populate with reused embeddings from existing cache
    if existing_index:
        for ck in chunk_keys:
            if ck in existing_index:
                chunk_index[ck] = existing_index[ck]

    # Collect texts that need new embeddings
    texts_to_embed = []
    keys_to_embed = []
    for ck, text in zip(chunk_keys, texts):
        if ck not in chunk_index:
            texts_to_embed.append(text)
            keys_to_embed.append(ck)

    if texts_to_embed:
        batch: list[str] = []
        batch_keys: list[str] = []
        batch_chars = 0
        batch_num = 0
        embedded_count = 0

        def _flush_batch() -> None:
            nonlocal batch, batch_keys, batch_chars, batch_num, embedded_count
            if not batch:
                return
            batch_num += 1
            response = client.embeddings.create(
                model=config.EMBEDDINGS_MODEL, input=batch
            )
            for bk, item in zip(batch_keys, response.data):
                chunk_index[bk] = item.embedding
            embedded_count += len(batch)
            print(f"  Batch {batch_num} done ({embedded_count}/{len(texts_to_embed)} chunks)")
            batch = []
            batch_keys = []
            batch_chars = 0

        start_time = time.time()
        for text, ck in zip(texts_to_embed, keys_to_embed):
            text_len = len(text)
            if batch and batch_chars + text_len > MAX_BATCH_CHARS:
                _flush_batch()
            batch.append(text)
            batch_keys.append(ck)
            batch_chars += text_len

        _flush_batch()
        elapsed = time.time() - start_time
        print(f"  Embedding took {elapsed:.1f}s")

    # Build the flat embeddings list (positional, for backwards compatibility)
    embeddings_flat = [chunk_index[ck] for ck in chunk_keys]

    payload = {
        "cache_key": key,
        "model": config.EMBEDDINGS_MODEL,
        "chunks": len(embeddings_flat),
        "embeddings": embeddings_flat,
        # Chunk-level index for incremental updates
        "chunk_index": chunk_index,
    }

    print(f"Writing {output_path} ...")
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f)

    size_mb = output_path.stat().st_size / (1024 * 1024)
    print(f"Done. {len(embeddings_flat)} embeddings written ({size_mb:.1f} MB)")
    if reused_count:
        print(f"  Reused: {reused_count}  |  New: {len(texts_to_embed)}")
    print(f"Cache key: {key}")
    print(f"\nThis file should be committed to git for instant first boot.")


if __name__ == "__main__":
    main()
