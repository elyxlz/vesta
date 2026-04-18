#!/usr/bin/env python3
"""Book search system: plain text search and semantic search across 183+ epub books."""

import json
import os
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional

SEARCH_DIR = Path.home() / "agent" / "data" / "skills" / "library" / "search"
CORPUS_DIR = SEARCH_DIR / "corpus"
INDEX_PATH = SEARCH_DIR / "corpus_index.json"
EMBEDDINGS_DIR = SEARCH_DIR / "embeddings"
CHUNKS_PATH = EMBEDDINGS_DIR / "chunks.json"
EMBEDDINGS_PATH = EMBEDDINGS_DIR / "embeddings.npy"

# Cache
_corpus_index = None
_corpus_cache = {}


def _load_index():
    global _corpus_index
    if _corpus_index is None:
        with open(INDEX_PATH, 'r', encoding='utf-8') as f:
            _corpus_index = json.load(f)
    return _corpus_index


def _load_corpus(filename: str) -> str:
    if filename not in _corpus_cache:
        path = CORPUS_DIR / filename
        with open(path, 'r', encoding='utf-8') as f:
            _corpus_cache[filename] = f.read()
    return _corpus_cache[filename]


def _find_chapter(book_entry: dict, position: int) -> str:
    """Find which chapter a position falls in."""
    # Account for the header lines (TITLE: ...\nAUTHOR: ...\n)
    for ch in book_entry['chapters']:
        if ch['offset'] <= position < ch['offset'] + ch['length']:
            return ch['title']
    # If not found exactly, find closest
    if book_entry['chapters']:
        for ch in reversed(book_entry['chapters']):
            if position >= ch['offset']:
                return ch['title']
        return book_entry['chapters'][0]['title']
    return 'Unknown'


def search_books(query: str, limit: int = 10, case_sensitive: bool = False) -> List[Dict]:
    """
    Full-text search across all books.

    Args:
        query: Search string (plain text or regex)
        limit: Maximum number of results
        case_sensitive: Whether search is case-sensitive

    Returns:
        List of dicts with: book, author, chapter, passage, match_start, match_end
    """
    index = _load_index()
    results = []
    flags = 0 if case_sensitive else re.IGNORECASE

    try:
        pattern = re.compile(re.escape(query), flags)
    except re.error:
        pattern = re.compile(re.escape(query), flags)

    for book in index:
        text = _load_corpus(book['filename'])

        for match in pattern.finditer(text):
            start = match.start()
            end = match.end()

            # Extract passage with context (±100 chars)
            ctx_start = max(0, start - 100)
            ctx_end = min(len(text), end + 100)
            passage = text[ctx_start:ctx_end]

            # Clean up passage boundaries to word boundaries
            if ctx_start > 0:
                space_idx = passage.find(' ')
                if space_idx != -1 and space_idx < 20:
                    passage = '...' + passage[space_idx + 1:]
            if ctx_end < len(text):
                space_idx = passage.rfind(' ')
                if space_idx != -1 and len(passage) - space_idx < 20:
                    passage = passage[:space_idx] + '...'

            chapter = _find_chapter(book, start)

            results.append({
                'book': book['title'],
                'author': book['author'],
                'chapter': chapter,
                'passage': passage.replace('\n', ' ').strip(),
                'filename': book['filename'],
                'match_start': start,
                'match_end': end,
            })

            if len(results) >= limit:
                break

        if len(results) >= limit:
            break

    return results[:limit]


def search_books_regex(pattern: str, limit: int = 10, flags: int = re.IGNORECASE) -> List[Dict]:
    """
    Regex search across all books.

    Args:
        pattern: Regular expression pattern
        limit: Maximum number of results
        flags: Regex flags (default: case-insensitive)

    Returns:
        List of dicts with: book, author, chapter, passage, match_start, match_end
    """
    index = _load_index()
    results = []
    compiled = re.compile(pattern, flags)

    for book in index:
        text = _load_corpus(book['filename'])

        for match in compiled.finditer(text):
            start = match.start()
            end = match.end()

            ctx_start = max(0, start - 100)
            ctx_end = min(len(text), end + 100)
            passage = text[ctx_start:ctx_end]

            if ctx_start > 0:
                space_idx = passage.find(' ')
                if space_idx != -1 and space_idx < 20:
                    passage = '...' + passage[space_idx + 1:]
            if ctx_end < len(text):
                space_idx = passage.rfind(' ')
                if space_idx != -1 and len(passage) - space_idx < 20:
                    passage = passage[:space_idx] + '...'

            chapter = _find_chapter(book, start)

            results.append({
                'book': book['title'],
                'author': book['author'],
                'chapter': chapter,
                'passage': passage.replace('\n', ' ').strip(),
                'filename': book['filename'],
                'match_start': start,
                'match_end': end,
            })

            if len(results) >= limit:
                break

        if len(results) >= limit:
            break

    return results[:limit]


# ─── Semantic Search ───────────────────────────────────────────────────────────

_semantic_loaded = False
_chunks_data = None
_embeddings_array = None
_model = None


def _load_semantic():
    """Load embeddings and chunks for semantic search."""
    global _semantic_loaded, _chunks_data, _embeddings_array
    if _semantic_loaded:
        return True

    if not EMBEDDINGS_PATH.exists() or not CHUNKS_PATH.exists():
        print("Semantic index not built yet. Run: python build_index.py")
        return False

    import numpy as np
    with open(CHUNKS_PATH, 'r', encoding='utf-8') as f:
        _chunks_data = json.load(f)
    _embeddings_array = np.load(str(EMBEDDINGS_PATH))
    _semantic_loaded = True
    return True


def _get_model():
    global _model
    if _model is None:
        from sentence_transformers import SentenceTransformer
        import torch
        device = 'cuda' if torch.cuda.is_available() else 'cpu'
        print(f"Loading model on {device}...")
        _model = SentenceTransformer('all-MiniLM-L6-v2', device=device)
    return _model


def semantic_search(query: str, limit: int = 5) -> List[Dict]:
    """
    Semantic search using embeddings.

    Args:
        query: Natural language query
        limit: Number of results to return

    Returns:
        List of dicts with: book, author, chapter, passage, score
    """
    if not _load_semantic():
        return []

    import numpy as np

    model = _get_model()
    query_embedding = model.encode([query], normalize_embeddings=True)[0]

    # Cosine similarity (embeddings are normalized)
    scores = _embeddings_array @ query_embedding
    top_indices = np.argsort(scores)[::-1][:limit]

    # Build title->filename mapping from corpus index
    index = _load_index()
    title_to_filename = {b['title']: b['filename'] for b in index}

    results = []
    for idx in top_indices:
        chunk = _chunks_data[idx]
        results.append({
            'book': chunk['book'],
            'author': chunk['author'],
            'chapter': chunk['chapter'],
            'passage': chunk['text'][:500],
            'score': float(scores[idx]),
            'filename': title_to_filename.get(chunk['book'], ''),
        })

    return results


# ─── CLI ───────────────────────────────────────────────────────────────────────

def _print_results(results, search_type="text"):
    if not results:
        print("No results found.")
        return

    for i, r in enumerate(results, 1):
        score_str = f"  [score: {r['score']:.4f}]" if 'score' in r else ''
        print(f"\n{'─'*80}")
        print(f"  Result {i}{score_str}")
        print(f"  Book:    {r['book']}")
        print(f"  Author:  {r['author']}")
        print(f"  Chapter: {r['chapter']}")
        print(f"  Passage: {r['passage'][:300]}")
    print(f"\n{'─'*80}")
    print(f"  {len(results)} result(s)")


def main():
    import argparse
    parser = argparse.ArgumentParser(description='Search across 183+ epub books')
    parser.add_argument('query', help='Search query text')
    parser.add_argument('--limit', '-n', type=int, default=10, help='Max results (default: 10)')
    parser.add_argument('--semantic', '-s', action='store_true', help='Use semantic search')
    parser.add_argument('--regex', '-r', action='store_true', help='Use regex search')
    parser.add_argument('--case-sensitive', '-c', action='store_true', help='Case-sensitive search')
    parser.add_argument('--json', '-j', action='store_true', help='Output as JSON')

    args = parser.parse_args()

    if args.semantic:
        print(f"Semantic search: \"{args.query}\"")
        results = semantic_search(args.query, limit=args.limit)
    elif args.regex:
        print(f"Regex search: \"{args.query}\"")
        results = search_books_regex(args.query, limit=args.limit)
    else:
        print(f"Text search: \"{args.query}\"")
        results = search_books(args.query, limit=args.limit, case_sensitive=args.case_sensitive)

    if args.json:
        print(json.dumps(results, indent=2, ensure_ascii=False))
    else:
        _print_results(results)


if __name__ == '__main__':
    main()
