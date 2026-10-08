"""Persian speech to text with word timings: Whisper (large) on our own server.

faster-whisper is imported on first use, so only the media worker needs it.
"""

from functools import lru_cache
from pathlib import Path

from ..config import get_settings
from ..i18n import patterns


@lru_cache
def _model():
    from faster_whisper import WhisperModel  # media worker only

    s = get_settings()
    return WhisperModel(s.whisper_model, device=s.whisper_device)


def transcribe(audio: Path, glossary: list[str] | None = None) -> dict:
    # The glossary goes in as the initial prompt: Whisper then prefers
    # those spellings for names it hears.
    prompt = patterns()["list_separator"].join(glossary or [])[:400] or None
    segments, info = _model().transcribe(str(audio), language="fa", word_timestamps=True,
                                          vad_filter=True, initial_prompt=prompt)
    out = []
    for seg in segments:
        words = [{"start": round(w.start, 3), "end": round(w.end, 3), "word": w.word.strip()}
                 for w in (seg.words or [])]
        out.append({"start": round(seg.start, 3), "end": round(seg.end, 3), "text": seg.text.strip(), "words": words})
    return {"language": info.language, "segments": out}


def plain_text(transcript: dict | None) -> str:
    return " ".join(seg["text"] for seg in (transcript or {}).get("segments", []))
