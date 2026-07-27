#!/usr/bin/env python3
"""Sanitize banned separators (em/en dash, ' - ', ' + ', ascii arrows) from a text file.
Usage: sanitize_dashes.py <file>   (in-place)  |  --check <file>  (report counts only)
The block_dashes rule only polices chat output; documents/emails/DOCX leak. Run this
on any DOCX-source .md, email body, or generated text before sending to the user."""
import re, sys

def sanitize(txt: str) -> str:
    # time/date ranges with en/em/hyphen -> hyphen-minus (acceptable inside a range token)
    txt = re.sub(r'(\d[:\.]\d+)\s*[–—]\s*(\d[:\.]\d+)', r'\1-\2', txt)
    txt = re.sub(r'(\d{4}-\d{2}-\d{2})\s*[–—]\s*(\d{4}-\d{2}-\d{2})', r'\1-\2', txt)
    # standalone em/en dash used as a separator -> colon
    txt = txt.replace(' — ', ': ').replace(' —', ':').replace('— ', ': ')
    txt = txt.replace(' – ', ': ').replace(' –', ':').replace('– ', ': ')
    txt = txt.replace('—', ':').replace('–', ':')
    # " - " word separator -> ", "  ([^\S\n] = whitespace except newline, so \n- bullet markers survive)
    txt = re.sub(r'[^\S\n]+-[^\S\n]+', ', ', txt)
    # " + " concept/name join -> ", " (Italian "e" handled case-by-case; comma is safe default)
    txt = re.sub(r'[^\S\n]+\+[^\S\n]+', ', ', txt)
    # ascii arrows -> " a " / " to "
    txt = txt.replace('->', ' a ').replace('→', ' a ')
    return txt

def count(txt: str) -> dict:
    return {
        'em_dash': len(re.findall(r'—', txt)),
        'en_dash': len(re.findall(r'–', txt)),
        'sep_dash': len(re.findall(r'[^\S\n]+-[^\S\n]+', txt)),
        'plus_join': len(re.findall(r'[^\S\n]+\+[^\S\n]+', txt)),
        'arrow': len(re.findall(r'->|→', txt)),
    }

if __name__ == '__main__':
    args = sys.argv[1:]
    check = '--check' in args
    if check: args.remove('--check')
    if not args:
        print(__doc__); sys.exit(1)
    for path in args:
        t = open(path, encoding='utf-8').read()
        before = count(t)
        if check:
            print(f"{path}: {before}")
            continue
        out = sanitize(t)
        after = count(out)
        open(path, 'w', encoding='utf-8').write(out)
        print(f"{path}: {before} -> {after}")
