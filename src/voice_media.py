from __future__ import annotations

import json
import shutil
import subprocess
import uuid
import wave
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

MAX_MEDIA_SECONDS = 300
ALLOWED_AUDIO = {".mp3", ".wav", ".m4a", ".ogg", ".aac"}
ALLOWED_VIDEO = {".mp4", ".mov", ".m4v", ".avi"}
ALLOWED_EXTENSIONS = ALLOWED_AUDIO | ALLOWED_VIDEO

ROOT = Path(__file__).resolve().parents[1]
MEDIA_ROOT = ROOT / "data" / "media"
UPLOAD_ROOT = MEDIA_ROOT / "uploads"
CLIP_ROOT = MEDIA_ROOT / "clips"
REPLY_ROOT = MEDIA_ROOT / "replies"
MANIFEST_PATH = MEDIA_ROOT / "manifest.json"


def _ensure_storage() -> None:
    for directory in (MEDIA_ROOT, UPLOAD_ROOT, CLIP_ROOT, REPLY_ROOT):
        directory.mkdir(parents=True, exist_ok=True)
    if not MANIFEST_PATH.exists():
        MANIFEST_PATH.write_text("[]\n", encoding="utf-8")


def _read_manifest() -> List[Dict[str, Any]]:
    _ensure_storage()
    try:
        with MANIFEST_PATH.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
            if isinstance(payload, list):
                return payload
    except json.JSONDecodeError:
        pass
    return []


def _write_manifest(entries: List[Dict[str, Any]]) -> None:
    _ensure_storage()
    with MANIFEST_PATH.open("w", encoding="utf-8") as handle:
        json.dump(entries, handle, indent=2)
        handle.write("\n")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _duration_from_wav(path: Path) -> Optional[float]:
    try:
        with wave.open(str(path), "rb") as wav:
            channels = wav.getnchannels()
            sample_width = wav.getsampwidth()
            frame_rate = wav.getframerate()
            frames = wav.getnframes()
            if frame_rate <= 0:
                return None
            return frames / frame_rate
    except (OSError, EOFError, ValueError):
        return None


def _ffprobe_duration(path: Path) -> Optional[float]:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return None

    try:
        result = subprocess.run(
            [
                ffprobe,
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return None
        return float(result.stdout.strip())
    except (TypeError, ValueError):
        return None


def _detect_media_type(path: Path) -> str:
    extension = path.suffix.lower()
    if extension in ALLOWED_AUDIO:
        return "audio"
    if extension in ALLOWED_VIDEO:
        return "video"
    raise ValueError(f"Unsupported media type: {extension}")


def _media_duration(path: Path) -> float:
    duration = _ffprobe_duration(path)
    if duration is not None:
        return float(duration)
    if path.suffix.lower() == ".wav":
        wav_duration = _duration_from_wav(path)
        if wav_duration is not None:
            return float(wav_duration)
    return 0.0


def validate_media(file_path: str | Path) -> Dict[str, Any]:
    """Validate a media file and return metadata, including duration in seconds."""
    candidate = Path(file_path)
    if not candidate.exists():
        raise FileNotFoundError(f"Media file not found: {candidate}")

    extension = candidate.suffix.lower()
    if extension not in ALLOWED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{extension}'. Allowed: {sorted(ALLOWED_EXTENSIONS)}"
        )

    media_type = _detect_media_type(candidate)
    duration = _media_duration(candidate)

    if duration > MAX_MEDIA_SECONDS:
        raise ValueError(
            f"Media exceeds the 5-minute cap. Duration={duration:.1f}s > {MAX_MEDIA_SECONDS}s"
        )

    return {
        "type": media_type,
        "original_name": candidate.name,
        "path": str(candidate),
        "duration_seconds": round(duration, 2),
        "status": "validated",
    }


def _unique_destination(directory: Path, original_name: str) -> Path:
    stem = Path(original_name).stem
    suffix = Path(original_name).suffix
    unique_id = uuid.uuid4().hex[:8]
    candidate = directory / f"{stem}_{unique_id}{suffix}"
    return candidate


def save_upload(file_path: str | Path, target_dir: str | Path = UPLOAD_ROOT) -> Dict[str, Any]:
    """Copy a user-uploaded media file into the repository-managed media folder."""
    source = Path(file_path)
    destination_dir = Path(target_dir)
    destination_dir.mkdir(parents=True, exist_ok=True)

    validated = validate_media(source)
    destination = _unique_destination(destination_dir, source.name)
    shutil.copy2(source, destination)

    manifest = _read_manifest()
    record = {
        "id": uuid.uuid4().hex,
        "type": validated["type"],
        "original_name": source.name,
        "path": str(destination),
        "duration_seconds": validated["duration_seconds"],
        "created_at": _now_iso(),
        "status": "uploaded",
    }
    manifest.append(record)
    _write_manifest(manifest)
    return record


def transcribe_audio(path: str | Path) -> Dict[str, Any]:
    """Placeholder transcription path: returns queued metadata if no local speech engine is available."""
    file_path = Path(path)
    validation = validate_media(file_path)
    if validation["type"] != "audio":
        raise ValueError("transcribe_audio expects an audio file")

    manifest = _read_manifest()
    result = {
        "file": str(file_path),
        "duration_seconds": validation["duration_seconds"],
        "status": "queued",
        "text": "",
        "provider": "local-placeholder",
    }

    for record in manifest:
        if record.get("path") == str(file_path):
            record["status"] = "transcribed"
            break
    _write_manifest(manifest)
    return result


def generate_voice_reply(text: str, voice: str = "default") -> str:
    """Create a placeholder voice reply file and return its path."""
    if not text or not text.strip():
        raise ValueError("Voice reply text cannot be empty")

    reply_name = f"frank_reply_{uuid.uuid4().hex[:8]}.txt"
    reply_path = REPLY_ROOT / reply_name
    reply_path.write_text(text.strip(), encoding="utf-8")

    manifest = _read_manifest()
    manifest.append(
        {
            "id": uuid.uuid4().hex,
            "type": "voice_reply",
            "original_name": reply_name,
            "path": str(reply_path),
            "duration_seconds": 0.0,
            "created_at": _now_iso(),
            "status": "ready",
            "voice": voice,
        }
    )
    _write_manifest(manifest)
    return str(reply_path)


def save_reply_audio(path: str | Path) -> Dict[str, Any]:
    """Track a generated audio response file in the manifest."""
    file_path = Path(path)
    if not file_path.exists():
        raise FileNotFoundError(f"Reply audio not found: {file_path}")

    manifest = _read_manifest()
    record = {
        "id": uuid.uuid4().hex,
        "type": "voice_reply",
        "original_name": file_path.name,
        "path": str(file_path),
        "duration_seconds": 0.0,
        "created_at": _now_iso(),
        "status": "ready",
    }
    manifest.append(record)
    _write_manifest(manifest)
    return record


def list_recent_media(limit: int = 20) -> List[Dict[str, Any]]:
    entries = _read_manifest()
    return list(reversed(entries))[: max(1, limit)]


def create_test_wav(path: str | Path, seconds: int = 1) -> Path:
    """Create a tiny valid WAV file for dry testing without requiring FFmpeg."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)

    sample_rate = 8000
    total_frames = sample_rate * seconds
    amplitude = 32767

    with wave.open(str(target), "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)

        # generate a simple sine-like wave by writing 16-bit PCM values
        data = bytearray()
        for i in range(total_frames):
            value = int(amplitude * 0.5 * __import__("math").sin(2 * __import__("math").pi * 440 * i / sample_rate))
            data.extend(int(value).to_bytes(2, byteorder="little", signed=True))
        wav_file.writeframes(data)

    return target


def run_dry_test() -> Dict[str, Any]:
    """Run a complete dry test flow for upload validation and reply generation."""
    _ensure_storage()
    test_path = UPLOAD_ROOT / "dry_test_audio.wav"
    create_test_wav(test_path, seconds=1)

    validated = validate_media(test_path)
    uploaded = save_upload(test_path)
    reply_path = generate_voice_reply("Frank dry test reply: voice enabled and media ready.")
    recent = list_recent_media(5)

    return {
        "validated": validated,
        "uploaded": uploaded,
        "reply_path": reply_path,
        "recent_media": recent,
    }


if __name__ == "__main__":
    print("Media storage root:", MEDIA_ROOT)
    print("Allowed extensions:", sorted(ALLOWED_EXTENSIONS))
    print("Max clip duration:", MAX_MEDIA_SECONDS, "seconds")
    print(json.dumps(run_dry_test(), indent=2))

