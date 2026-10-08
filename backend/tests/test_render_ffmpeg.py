"""The real FFmpeg path: cut, reframe, burn Persian subtitles, cover.

Runs only where ffmpeg is installed (the media worker image); elsewhere it
is skipped, and says so. Set GE_TEST_FONTS_DIR to a folder with
Vazirmatn-Regular.ttf to render with the brand font.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest

from growth_engine.media import ffmpeg, render

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg is not installed")

TRANSCRIPT = {"segments": [
    {"start": 0.6, "end": 2.6, "text": "از قله‌ی شتری", "words": [
        {"start": 0.6, "end": 1.2, "word": "از"}, {"start": 1.2, "end": 1.9, "word": "قله‌ی"},
        {"start": 1.9, "end": 2.6, "word": "شتری"}]},
    {"start": 5.2, "end": 7.4, "text": "کویر تا افق پیداست ۱۴۰۵", "words": [
        {"start": 5.2, "end": 5.8, "word": "کویر"}, {"start": 5.8, "end": 6.1, "word": "تا"},
        {"start": 6.1, "end": 6.6, "word": "افق"}, {"start": 6.6, "end": 7.0, "word": "پیداست"},
        {"start": 7.0, "end": 7.4, "word": "۱۴۰۵"}]},
]}


@pytest.fixture
def source(tmp_path) -> Path:
    """8 s of landscape video: tone, 2.5 s of silence, tone again."""
    path = tmp_path / "raw.mp4"
    subprocess.run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=25:duration=8",
        "-f", "lavfi", "-i", "sine=frequency=440:duration=8",
        "-filter_complex", "[1:a]volume='if(between(t,2.8,5.0),0,1)':eval=frame[a]",
        "-map", "0:v", "-map", "[a]", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(path),
    ], check=True)
    return path


def test_a_raw_video_becomes_short_story_full_and_cover(source, tmp_path):
    probe = ffmpeg.probe(source)
    assert probe.has_audio and round(probe.duration) == 8
    silences = ffmpeg.detect_silences(source, probe.duration)
    assert any(a < 3.0 and b > 4.8 for a, b in silences)

    spec = {"min_s": 3, "max_s": 5, "aspects": ["9:16", "16:9"], "subtitle_mode": "word"}
    specs = render.plan_renders(probe.duration, silences, TRANSCRIPT, spec)
    fonts = os.environ.get("GE_TEST_FONTS_DIR")
    look = render.BrandLook(font="Vazirmatn", text_color="#FFFFFF", box_color="#1F2A44",
                            highlight_color="#C9A66B", fonts_dir=Path(fonts) if fonts else None)
    work = tmp_path / "work"
    work.mkdir()
    out = render.render(source, work, probe, specs, look, overlay="کوه و کویر · ۱۴ آذر", cover_title="صعود شتری",
                        music=None)

    short = ffmpeg.probe(out.files["short"])
    assert (short.width, short.height) == (1080, 1920)
    assert short.duration <= 5.5
    full = ffmpeg.probe(out.files["full"])
    assert (full.width, full.height) == (1920, 1080)
    assert full.duration < probe.duration - 1.5  # the silence is gone
    srt = out.files["srt"].read_text(encoding="utf-8")
    assert "از قله‌ی شتری" in srt and "-->" in srt
    assert out.files["cover"].stat().st_size > 1000
    keep = os.environ.get("GE_KEEP_RENDERS")
    if keep:
        for name, path in out.files.items():
            shutil.copy(path, Path(keep) / f"{name}{path.suffix}")
