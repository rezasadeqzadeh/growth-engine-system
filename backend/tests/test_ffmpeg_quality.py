"""The render's quality chain: picture clean-up, voice levelling and the encode settings."""

from pathlib import Path

from growth_engine.media import ffmpeg


def _render_args(monkeypatch, **kw) -> list[str]:
    calls = []
    monkeypatch.setattr(ffmpeg, "run", lambda args, timeout=1800: calls.append(args) or "")
    ffmpeg.cut_and_frame(Path("in.mov"), Path("out.mp4"), [(0.0, 2.0), (3.0, 5.0)], "9:16", **kw)
    return calls[0]


def test_picture_is_cleaned_before_framing_and_encoded_high_quality(monkeypatch):
    args = _render_args(monkeypatch)
    graph = args[args.index("-filter_complex") + 1]
    assert f"[cv]{ffmpeg.ENHANCE},split" in graph
    assert "flags=lanczos" in graph
    assert args[args.index("-crf") + 1] == "17" and args[args.index("-preset") + 1] == "slow"


def test_voice_is_levelled_and_mixed_under_music(monkeypatch):
    args = _render_args(monkeypatch, music=Path("bgm.mp3"))
    graph = args[args.index("-filter_complex") + 1]
    assert f"[ca]{ffmpeg.VOICE}[voice]" in graph and "[voice][bgm]amix" in graph


def test_silent_footage_gets_no_voice_chain(monkeypatch):
    args = _render_args(monkeypatch, has_audio=False)
    assert "loudnorm" not in args[args.index("-filter_complex") + 1]
