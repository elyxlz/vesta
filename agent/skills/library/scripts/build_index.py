#!/usr/bin/env python3
"""Build semantic search embeddings index for the book corpus."""

import json
import time
from pathlib import Path

SEARCH_DIR = Path.home() / "agent" / "data" / "skills" / "library" / "search"
CORPUS_DIR = SEARCH_DIR / "corpus"
INDEX_PATH = SEARCH_DIR / "corpus_index.json"
EMBEDDINGS_DIR = SEARCH_DIR / "embeddings"
CHUNKS_PATH = EMBEDDINGS_DIR / "chunks.json"
EMBEDDINGS_PATH = EMBEDDINGS_DIR / "embeddings.npy"
PROGRESS_PATH = EMBEDDINGS_DIR / "progress.json"

# Ensure directories exist
CORPUS_DIR.mkdir(parents=True, exist_ok=True)
EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)

CHUNK_WORDS = 500
CHUNK_OVERLAP = 50  # words overlap between chunks
MODEL_NAME = 'all-MiniLM-L6-v2'
BATCH_SIZE = 256


def chunk_text(text: str, book_title: str, author: str, chapters: list) -> list:
    """Split text into ~500-word chunks with metadata."""
    chunks = []
    words = text.split()

    if not words:
        return chunks

    # Build a map: word_index -> chapter_title
    # We do this by finding chapter offsets in character space and mapping to word space
    char_to_word = {}
    char_pos = 0
    for wi, w in enumerate(words):
        idx = text.find(w, char_pos)
        if idx >= 0:
            char_to_word[idx] = wi
            char_pos = idx + len(w)

    # For each chapter, find its word range
    chapter_word_ranges = []
    for ch in chapters:
        ch_offset = ch['offset']
        # Find nearest word index
        best_wi = 0
        best_dist = float('inf')
        for ci, wi in char_to_word.items():
            if abs(ci - ch_offset) < best_dist:
                best_dist = abs(ci - ch_offset)
                best_wi = wi
        chapter_word_ranges.append((best_wi, ch['title']))

    def get_chapter_for_word(word_idx):
        ch_title = chapters[0]['title'] if chapters else 'Unknown'
        for start_wi, title in chapter_word_ranges:
            if word_idx >= start_wi:
                ch_title = title
            else:
                break
        return ch_title

    # Create chunks
    i = 0
    while i < len(words):
        end = min(i + CHUNK_WORDS, len(words))
        chunk_words = words[i:end]
        chunk_text_str = ' '.join(chunk_words)

        # Skip very short chunks (< 30 words) unless it's the last
        if len(chunk_words) < 30 and i > 0:
            break

        chapter = get_chapter_for_word(i)

        chunks.append({
            'book': book_title,
            'author': author,
            'chapter': chapter,
            'word_offset': i,
            'text': chunk_text_str,
        })

        i += CHUNK_WORDS - CHUNK_OVERLAP

    return chunks


def build_chunks():
    """Build all chunks from corpus."""
    with open(INDEX_PATH, encoding='utf-8') as f:
        index = json.load(f)

    all_chunks = []
    for i, book in enumerate(index):
        corpus_path = CORPUS_DIR / book['filename']
        with open(corpus_path, encoding='utf-8') as f:
            text = f.read()

        # Skip the TITLE/AUTHOR header lines
        lines = text.split('\n', 2)
        if len(lines) > 2:
            text = lines[2]

        chunks = chunk_text(text, book['title'], book['author'], book['chapters'])
        all_chunks.extend(chunks)

        if (i + 1) % 20 == 0 or i == 0:
            print(f"  [{i+1}/{len(index)}] {book['title']}: {len(chunks)} chunks")

    print(f"\nTotal chunks: {len(all_chunks)}")
    return all_chunks


def build_embeddings(chunks: list, resume_from: int = 0):
    """Generate embeddings for all chunks."""
    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer

    device = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f"Using device: {device}")
    if device == 'cuda':
        print(f"GPU: {torch.cuda.get_device_name(0)}")

    print(f"Loading model: {MODEL_NAME}")
    model = SentenceTransformer(MODEL_NAME, device=device)

    texts = [c['text'] for c in chunks]
    total = len(texts)

    # Check for existing partial embeddings
    if resume_from > 0 and EMBEDDINGS_PATH.exists():
        print(f"Resuming from chunk {resume_from}/{total}")
        existing = np.load(str(EMBEDDINGS_PATH))
        embeddings_list = [existing]
        start = resume_from
    else:
        embeddings_list = []
        start = 0

    print(f"Encoding {total - start} chunks in batches of {BATCH_SIZE}...")
    t0 = time.time()

    for batch_start in range(start, total, BATCH_SIZE):
        batch_end = min(batch_start + BATCH_SIZE, total)
        batch_texts = texts[batch_start:batch_end]

        batch_embeddings = model.encode(
            batch_texts,
            normalize_embeddings=True,
            show_progress_bar=False,
            batch_size=BATCH_SIZE,
        )
        embeddings_list.append(batch_embeddings)

        elapsed = time.time() - t0
        done = batch_end - start
        rate = done / elapsed if elapsed > 0 else 0
        eta = (total - batch_end) / rate if rate > 0 else 0

        if (batch_end - start) % (BATCH_SIZE * 4) == 0 or batch_end == total:
            print(f"  [{batch_end}/{total}] {rate:.0f} chunks/s, ETA: {eta:.0f}s")

            # Save progress
            partial = np.vstack(embeddings_list)
            np.save(str(EMBEDDINGS_PATH), partial)
            with open(PROGRESS_PATH, 'w') as f:
                json.dump({'completed': batch_end, 'total': total}, f)

    all_embeddings = np.vstack(embeddings_list)
    print(f"\nEmbeddings shape: {all_embeddings.shape}")
    print(f"Total time: {time.time() - t0:.1f}s")

    return all_embeddings


def main():
    EMBEDDINGS_DIR.mkdir(parents=True, exist_ok=True)

    # Check for resume
    resume_from = 0
    if PROGRESS_PATH.exists() and CHUNKS_PATH.exists():
        with open(PROGRESS_PATH) as f:
            progress = json.load(f)
        resume_from = progress.get('completed', 0)
        print(f"Found progress file: {resume_from} chunks already done")

    # Step 1: Build chunks
    if CHUNKS_PATH.exists() and resume_from > 0:
        print("Loading existing chunks...")
        with open(CHUNKS_PATH, encoding='utf-8') as f:
            all_chunks = json.load(f)
        print(f"Loaded {len(all_chunks)} chunks")
    else:
        print("Building chunks from corpus...")
        all_chunks = build_chunks()
        with open(CHUNKS_PATH, 'w', encoding='utf-8') as f:
            json.dump(all_chunks, f, ensure_ascii=False)
        print(f"Saved chunks to {CHUNKS_PATH}")

    # Step 2: Build embeddings
    print("\nBuilding embeddings...")
    embeddings = build_embeddings(all_chunks, resume_from=resume_from)

    # Save final
    import numpy as np
    np.save(str(EMBEDDINGS_PATH), embeddings)

    # Clean up progress file
    if PROGRESS_PATH.exists():
        PROGRESS_PATH.unlink()

    print("\nDone!")
    print(f"  Chunks: {CHUNKS_PATH} ({len(all_chunks)} chunks)")
    print(f"  Embeddings: {EMBEDDINGS_PATH} ({embeddings.shape})")
    print(f"  Size: {EMBEDDINGS_PATH.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == '__main__':
    main()
