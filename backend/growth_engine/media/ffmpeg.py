"""Thin wrappers over ffmpeg/ffprobe. Every command is built as a list
(never a shell string) and every failure raises MediaError."""

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

ASPECTS = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080)}


class MediaError(RuntimeError):
    pass


def run(args: list[str], timeout: int = 1800) -> str:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise MediaError(f"{args[0]} is not installed") from exc
    except subprocess.TimeoutExpired as exc:
        raise MediaError(f"{args[0]} timed out") from exc
    if proc.returncode != 0:
        raise MediaError(f"{args[0]} failed: {proc.stderr[-800:]}")
    return proc.stdout + proc.stderr


@dataclass
class Probe:
    duration: float
    width: int
    height: int
    has_audio: bool


def probe(path: Path) -> Probe:
    out = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", str(path)])
    data = json.loads(out[out.find("{"):])
    video = next((st for st in data.get("streams", []) if st.get("codec_type") == "video"), None)
    if video is None:
        raise MediaError("The file has no video stream")
    has_audio = any(st.get("codec_type") == "audio" for st in data.get("streams", []))
    return Probe(float(data["format"]["duration"]), int(video["width"]), int(video["height"]), has_audio)


_SIL_START = re.compile(r"silence_start: ([\d.]+)")
_SIL_END = re.compile(r"silence_end: ([\d.]+)")


def parse_silences(log: str, duration: float) -> list[tuple[float, float]]:
    starts = [float(x) for x in _SIL_START.findall(log)]
    ends = [float(x) for x in _SIL_END.findall(log)]
    pairs = []
    for i, start in enumerate(starts):
        end = ends[i] if i < len(ends) else duration
        pairs.append((max(0.0, start), min(duration, end)))
    return pairs


def detect_silences(path: Path, duration: float, noise_db: int = -32, min_s: float = 0.7) -> list[tuple[float, float]]:
    log = run(["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af",
               f"silencedetect=noise={noise_db}dB:d={min_s}", "-f", "null", "-"])
    return parse_silences(log, duration)


def cut_and_frame(src: Path, dst: Path, ranges: list[tuple[float, float]], aspect: str,
                  subtitles: Path | None = None, fonts_dir: Path | None = None,
                  logo: Path | None = None, music: Path | None = None, has_audio: bool = True) -> None:
    """Keep `ranges`, fill the frame for `aspect` (blurred background, no
    black bars), burn subtitles, put the logo top-left as a watermark."""
    w, h = ASPECTS[aspect]
    parts, labels = [], []
    for i, (a, b) in enumerate(ranges):
        parts.append(f"[0:v]trim={a:.3f}:{b:.3f},setpts=PTS-STARTPTS[v{i}]")
        if has_audio:
            parts.append(f"[0:a]atrim={a:.3f}:{b:.3f},asetpts=PTS-STARTPTS[a{i}]")
        labels.append(f"[v{i}]" + (f"[a{i}]" if has_audio else ""))
    n = len(ranges)
    parts.append("".join(labels) + f"concat=n={n}:v=1:a={1 if has_audio else 0}[cv]" + ("[ca]" if has_audio else ""))
    parts.append(f"[cv]{_fill_frame(w, h)}[framed]")
    last = "framed"
    if subtitles is not None:
        fonts = f":fontsdir={_escape(fonts_dir)}" if fonts_dir else ""
        parts.append(f"[{last}]ass={_escape(subtitles)}{fonts}[subbed]")
        last = "subbed"
    inputs = ["-i", str(src)]
    if logo is not None:
        inputs += ["-i", str(logo)]
        parts.append(f"[1:v]scale={w // 7}:-1,format=rgba,colorchannelmixer=aa=0.85[lg]")
        parts.append(f"[{last}][lg]overlay=40:40[wm]")
        last = "wm"
    audio_map: list[str] = []
    if music is not None:
        music_idx = 2 if logo is not None else 1
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        if has_audio:
            parts.append(f"[{music_idx}:a]volume=0.25[bgm];[ca][bgm]amix=inputs=2:duration=first[mix]")
        else:
            parts.append(f"[{music_idx}:a]volume=0.6,atrim=0:{sum(b - a for a, b in ranges):.3f}[mix]")
        audio_map = ["-map", "[mix]"]
    elif has_audio:
        audio_map = ["-map", "[ca]"]
    run(["ffmpeg", "-y", "-hide_banner", *inputs, "-filter_complex", ";".join(parts),
         "-map", f"[{last}]", *audio_map, "-c:v", "libx264", "-preset", "medium", "-crf", "21",
         "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dst)])


def frame_at(src: Path, dst: Path, second: float) -> None:
    run(["ffmpeg", "-y", "-hide_banner", "-ss", f"{second:.2f}", "-i", str(src), "-frames:v", "1", str(dst)])


def _fill_frame(w: int, h: int) -> str:
    # The frame filled for the aspect: blurred copy behind, the whole picture in front.
    return (f"split[bgsrc][fgsrc];[bgsrc]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},"
            f"boxblur=24:2[bg];[fgsrc]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
            "[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1")


def best_frame(src: Path, dst: Path, aspect: str = "9:16", start: float = 0.0, length: float | None = None) -> None:
    """The most representative frame (ffmpeg's `thumbnail` filter) of the
    raw footage in [start, start + length], framed for `aspect`. Taken from
    the raw video so no subtitle or overlay is baked into the cover."""
    w, h = ASPECTS[aspect]
    window = ["-ss", f"{start:.2f}"] + (["-t", f"{length:.2f}"] if length else [])
    run(["ffmpeg", "-y", "-hide_banner", *window, "-i", str(src), "-vf", f"thumbnail=150,{_fill_frame(w, h)}",
         "-frames:v", "1", str(dst)])


def burn_on_image(src: Path, dst: Path, ass: Path, fonts_dir: Path | None) -> None:
    fonts = f":fontsdir={_escape(fonts_dir)}" if fonts_dir else ""
    run(["ffmpeg", "-y", "-hide_banner", "-loop", "1", "-i", str(src), "-vf", f"ass={_escape(ass)}{fonts}",
         "-frames:v", "1", str(dst)])


def extract_audio(src: Path, dst: Path) -> None:
    run(["ffmpeg", "-y", "-hide_banner", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(dst)])


def _escape(path: Path | None) -> str:
    # Filter-graph argument escaping: backslash, colon and quote are special.
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")
