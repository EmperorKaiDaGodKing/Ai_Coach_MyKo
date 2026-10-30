#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.voice_media import run_dry_test, save_upload, validate_media, generate_voice_reply


def main() -> None:
    parser = argparse.ArgumentParser(description="Run Frank dry test for media upload and voice reply flow")
    parser.add_argument("--audio", type=str, default=None, help="Optional path to an audio file to validate/upload")
    parser.add_argument("--text", type=str, default="Frank dry test: media and voice are active.", help="Reply text for the voice reply")
    args = parser.parse_args()

    if args.audio:
        file_path = Path(args.audio)
        print(json.dumps(validate_media(file_path), indent=2))
        print(json.dumps(save_upload(file_path), indent=2))
        print(generate_voice_reply(args.text))
        return

    print(json.dumps(run_dry_test(), indent=2))


if __name__ == "__main__":
    main()
