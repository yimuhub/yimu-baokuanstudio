#!/usr/bin/env python3
"""Translate all 784 missing strings in batches using core.llm.chat with retry and fallback."""
import json
import os
import re
import time
from core.llm import chat
from scripts.trans_rules_part1 import TRANS_MAP

CHINESE_PATTERN = re.compile(r'[\u4e00-\u9fa5]')

def load_progress():
    if os.path.exists('translated_missing.json'):
        with open('translated_missing.json', 'r', encoding='utf-8') as f:
            return json.load(f)
    return {}

def save_progress(data):
    with open('translated_missing.json', 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def main():
    with open('missing_strings.json', 'r', encoding='utf-8') as f:
        missing = json.load(f)

    progress = load_progress()
    # Preload from TRANS_MAP
    for k, v in TRANS_MAP.items():
        if k in missing and k not in progress:
            progress[k] = v

    todo = [s for s in missing if s not in progress]
    print(f"Total to translate: {len(missing)}, already done: {len(progress)}, remaining: {len(todo)}")

    batch_size = 35
    for i in range(0, len(todo), batch_size):
        batch = todo[i:i+batch_size]
        print(f"\nProcessing batch {i//batch_size + 1}/{(len(todo) + batch_size - 1)//batch_size} ({len(batch)} items)...")
        
        prompt = (
            "You are a professional software localization translator for a modern AI content creation platform.\n"
            "Translate each Chinese UI text into clear, natural, and concise English.\n"
            "Preserve all emojis (like 🎬, 🚀, 💎, etc.), symbols, punctuation marks, brackets, placeholders, and newlines.\n"
            "Return ONLY a single valid JSON object mapping each exact Chinese string to its English translation.\n"
            "Do NOT include markdown formatting like ```json or any conversational text.\n"
            "Input JSON list:\n"
            f"{json.dumps(batch, ensure_ascii=False)}"
        )

        success = False
        for attempt in range(3):
            try:
                resp = chat([{"role": "user", "content": prompt}], temperature=0.1, timeout_s=45)
                # Clean response
                resp = resp.strip()
                if resp.startswith("```"):
                    lines = resp.splitlines()
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1].startswith("```"):
                        lines = lines[:-1]
                    resp = "\n".join(lines).strip()
                
                parsed = json.loads(resp)
                if isinstance(parsed, dict):
                    valid_count = 0
                    for k, v in parsed.items():
                        if k in batch and isinstance(v, str) and not CHINESE_PATTERN.search(v):
                            progress[k] = v
                            valid_count += 1
                    print(f"  Batch successfully translated {valid_count}/{len(batch)} items.")
                    save_progress(progress)
                    success = True
                    break
            except Exception as e:
                print(f"  Attempt {attempt+1} failed: {e}")
                time.sleep(2)
        
        if not success:
            print(f"  Batch {i} failed after 3 attempts, will continue to next batch...")

    # Report current status
    still_missing = [s for s in missing if s not in progress or CHINESE_PATTERN.search(progress[s])]
    print(f"\nFinished batch processing. Translated: {len(progress)}/{len(missing)}. Unresolved: {len(still_missing)}")

if __name__ == '__main__':
    main()
