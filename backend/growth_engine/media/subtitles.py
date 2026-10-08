"""Persian subtitles: ASS for burning in (brand font and colours, right to
left) and SRT as a separate file for Aparat.

libass shapes Persian through HarfBuzz and orders it through FriBidi, but
only detects the paragraph direction when a style's Encoding is -1; with
Encoding 1 a Persian line came out with its words in left-to-right order.
Each line also starts with RLM, so a line that opens with a digit or a
Latin word is still laid out right to left.
"""

from dataclasses import dataclass

from .edit_plan import Range, remap

RLM = "‏"
MAX_CHARS = 42
WORDS_PER_CHUNK = 3


@dataclass
class Cue:
    start: float
    end: float
    text: str
    words: list[tuple[float, float, str]] | None = None


def _words(transcript: dict) -> list[tuple[float, float, str]]:
    out = []
    for seg in transcript.get("segments", []):
        words = seg.get("words")
        if words:
            out += [(w["start"], w["end"], w["word"].strip()) for w in words if w["word"].strip()]
        elif seg.get("text", "").strip():
            out.append((seg["start"], seg["end"], seg["text"].strip()))
    return out


def build_cues(transcript: dict | None, ranges: list[Range], mode: str) -> list[Cue]:
    """Cues on the OUTPUT timeline. A word cut away by the edit is dropped."""
    if not transcript or mode == "none":
        return []
    mapped = []  # (out_start, out_end, word, source_start, source_end)
    for start, end, word in _words(transcript):
        a, b = remap(start, ranges), remap(end, ranges)
        if a is not None and b is not None and b > a:
            mapped.append((a, b, word, start, end))
    cues: list[Cue] = []
    group: list[tuple] = []

    def flush() -> None:
        if group:
            words = [(a, b, w) for a, b, w, _, _ in group]
            cues.append(Cue(group[0][0], group[-1][1], " ".join(w for _, _, w in words), words))
            group.clear()

    for item in mapped:
        # A pause in the speech ends the line (measured on the source: the cut removed the silence).
        if group and item[3] - group[-1][4] > 1.0:
            flush()
        if mode == "word" and len(group) >= WORDS_PER_CHUNK:
            flush()
        if mode != "word" and len(" ".join(g[2] for g in group + [item])) > MAX_CHARS:
            flush()
        group.append(item)
    flush()
    return cues


def _ass_time(t: float) -> str:
    cs = int(round(t * 100))
    h, rem = divmod(cs, 360000)
    m, rem = divmod(rem, 6000)
    s, cs = divmod(rem, 100)
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))
    h, rem = divmod(ms, 3600000)
    m, rem = divmod(rem, 60000)
    s, ms = divmod(rem, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def ass_color(hex_color: str, alpha: int = 0) -> str:
    """#RRGGBB -> &HAABBGGRR (ASS colour order)."""
    r, g, b = hex_color[1:3], hex_color[3:5], hex_color[5:7]
    return f"&H{alpha:02X}{b}{g}{r}".upper()


def _escape(text: str) -> str:
    return text.replace("\\", "").replace("{", "(").replace("}", ")").replace("\n", " ")


def build_ass(cues: list[Cue], *, width: int, height: int, font: str, text_color: str, box_color: str,
              highlight_color: str, mode: str, overlay: str | None = None, overlay_until: float | None = None) -> str:
    size = int(height * (0.045 if width < height else 0.06))
    # Karaoke (\kf) paints from SecondaryColour to PrimaryColour as each word is said.
    primary = highlight_color if mode == "word" else text_color
    head = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "WrapStyle: 0", "ScaledBorderAndShadow: yes", "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, "
        "Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding",
        # BorderStyle 3 = opaque box behind the text: readable on any footage.
        f"Style: Sub,{font},{size},{ass_color(primary)},{ass_color(text_color)},"
        f"{ass_color(box_color, 0x40)},{ass_color(box_color, 0x40)},-1,0,0,0,100,100,0,0,3,12,0,2,60,60,"
        f"{int(height * 0.14)},-1",
        f"Style: Title,{font},{int(size * 1.25)},{ass_color(text_color)},{ass_color(text_color)},"
        f"{ass_color(box_color, 0x20)},{ass_color(box_color, 0x20)},-1,0,0,0,100,100,0,0,3,16,0,8,60,60,"
        f"{int(height * 0.08)},-1",
        "", "[Events]", "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    events = []
    if overlay:
        end = overlay_until if overlay_until is not None else (cues[-1].end if cues else 5.0)
        events.append(f"Dialogue: 1,{_ass_time(0)},{_ass_time(max(end, 3.0))},Title,,0,0,0,,{RLM}{_escape(overlay)}")
    for cue in cues:
        if mode == "word" and cue.words:
            # Karaoke: each word lights up (secondary -> primary colour) as it is said.
            parts = [f"{{\\kf{max(1, int(round((b - a) * 100)))}}}{_escape(w)}" for a, b, w in cue.words]
            text = " ".join(parts)
        else:
            text = _escape(cue.text)
        events.append(f"Dialogue: 0,{_ass_time(cue.start)},{_ass_time(cue.end)},Sub,,0,0,0,,{RLM}{text}")
    return "\n".join(head + events) + "\n"


def build_srt(cues: list[Cue]) -> str:
    blocks = [f"{i}\n{_srt_time(c.start)} --> {_srt_time(c.end)}\n{c.text}\n" for i, c in enumerate(cues, 1)]
    return "\n".join(blocks)


def title_ass(text: str, *, width: int, height: int, font: str, text_color: str, box_color: str) -> str:
    """A one-frame ASS that writes the cover title (used on the chosen frame)."""
    return build_ass([], width=width, height=height, font=font, text_color=text_color, box_color=box_color,
                     highlight_color=text_color, mode="sentence", overlay=text, overlay_until=10.0)
