"""From one raw video to every finished file a post needs.

`plan_renders` decides (pure, tested); `render` runs FFmpeg for the plan.
Outputs:
  short  9:16, the recipe's length window: reels, messengers, site
  story  9:16, the best 15 seconds
  full   16:9, everything minus silences, with an SRT beside it (Aparat)
  cover  the most representative frame with the title written on it
"""

from dataclasses import dataclass, field
from pathlib import Path

from . import edit_plan, ffmpeg, subtitles
from .edit_plan import Range

STORY_MAX_S = 15.0


@dataclass
class RenderSpec:
    name: str
    aspect: str
    ranges: list[Range]
    cues: list[subtitles.Cue]
    subtitle_mode: str


@dataclass
class BrandLook:
    font: str
    text_color: str
    box_color: str
    highlight_color: str
    logo: Path | None = None
    fonts_dir: Path | None = None


@dataclass
class Rendered:
    files: dict[str, Path] = field(default_factory=dict)
    durations: dict[str, float] = field(default_factory=dict)


def plan_renders(duration: float, silences: list[Range], transcript: dict | None, video_spec: dict) -> list[RenderSpec]:
    has_speech = bool(transcript and transcript.get("segments"))
    mode = video_spec.get("subtitle_mode", "sentence") if has_speech else "none"
    kept = edit_plan.keep_ranges(duration, silences if has_speech else [])
    min_s, max_s = float(video_spec.get("min_s", 10)), float(video_spec.get("max_s", 60))
    short = edit_plan.choose_window(kept, transcript, min_s, max_s, speech=has_speech)
    story = edit_plan.choose_window(short, transcript, min(min_s, STORY_MAX_S), STORY_MAX_S, speech=has_speech)
    specs = [
        RenderSpec("short", "9:16", short, subtitles.build_cues(transcript, short, mode), mode),
        RenderSpec("story", "9:16", story, subtitles.build_cues(transcript, story, mode), mode),
    ]
    if "16:9" in video_spec.get("aspects", []):
        # The full version is for reading along: sentence subtitles, always.
        full_mode = "sentence" if has_speech else "none"
        specs.append(RenderSpec("full", "16:9", kept, subtitles.build_cues(transcript, kept, full_mode), full_mode))
    return specs


def render(src: Path, workdir: Path, probe: ffmpeg.Probe, specs: list[RenderSpec], look: BrandLook,
           overlay: str | None, cover_title: str, music: Path | None) -> Rendered:
    out = Rendered()
    for spec in specs:
        w, h = ffmpeg.ASPECTS[spec.aspect]
        ass_path = None
        if spec.cues or overlay:
            ass_path = workdir / f"{spec.name}.ass"
            ass_path.write_text(subtitles.build_ass(
                spec.cues, width=w, height=h, font=look.font, text_color=look.text_color,
                box_color=look.box_color, highlight_color=look.highlight_color, mode=spec.subtitle_mode,
                overlay=overlay, overlay_until=min(4.0, edit_plan.output_duration(spec.ranges))), encoding="utf-8")
        dst = workdir / f"{spec.name}.mp4"
        ffmpeg.cut_and_frame(src, dst, spec.ranges, spec.aspect, subtitles=ass_path, fonts_dir=look.fonts_dir,
                             logo=look.logo, music=music, has_audio=probe.has_audio)
        out.files[spec.name] = dst
        out.durations[spec.name] = edit_plan.output_duration(spec.ranges)
        if spec.name == "full" and spec.cues:
            srt = workdir / "full.srt"
            srt.write_text(subtitles.build_srt(spec.cues), encoding="utf-8")
            out.files["srt"] = srt

    frame = workdir / "frame.png"
    short = next(sp for sp in specs if sp.name == "short")
    ffmpeg.best_frame(src, frame, "9:16", short.ranges[0][0], short.ranges[-1][1] - short.ranges[0][0])
    cover_ass = workdir / "cover.ass"
    cover_ass.write_text(subtitles.title_ass(cover_title, width=1080, height=1920, font=look.font,
                                             text_color=look.text_color, box_color=look.box_color), encoding="utf-8")
    cover = workdir / "cover.jpg"
    ffmpeg.burn_on_image(frame, cover, cover_ass, look.fonts_dir)
    out.files["cover"] = cover
    out.files["frame"] = frame
    return out


def sample_frames(src: Path, workdir: Path, duration: float, count: int = 5) -> list[Path]:
    frames = []
    for i in range(count):
        path = workdir / f"sample{i}.jpg"
        ffmpeg.frame_at(src, path, duration * (i + 1) / (count + 1))
        frames.append(path)
    return frames
