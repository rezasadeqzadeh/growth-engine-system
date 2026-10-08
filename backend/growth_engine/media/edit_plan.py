"""Smart cut, as pure functions: what to keep, which window becomes the
short version, and where each source moment lands after cutting."""

Range = tuple[float, float]

EDGE_TRIM_S = 0.5  # the first/last half second is usually the shaky press of the record button


def keep_ranges(duration: float, silences: list[Range], pad: float = 0.15, min_keep: float = 0.4) -> list[Range]:
    """Everything except the silences, padded so words are not clipped."""
    start_at, end_at = min(EDGE_TRIM_S, duration / 4), max(duration - EDGE_TRIM_S, duration * 3 / 4)
    out: list[Range] = []
    cursor = start_at
    for s_start, s_end in sorted(silences):
        a, b = cursor, min(s_start + pad, end_at)
        if b - a >= min_keep:
            out.append((round(a, 3), round(b, 3)))
        cursor = max(cursor, s_end - pad)
    if end_at - cursor >= min_keep:
        out.append((round(cursor, 3), round(end_at, 3)))
    return out or [(0.0, duration)]


def _words_in(a: float, b: float, transcript: dict | None) -> int:
    if not transcript:
        return 0
    count = 0
    for seg in transcript.get("segments", []):
        for word in seg.get("words") or [{"start": seg["start"], "end": seg["end"]}]:
            if a <= word["start"] and word["end"] <= b:
                count += 1
    return count


def choose_window(ranges: list[Range], transcript: dict | None, min_s: float, max_s: float,
                  speech: bool = True) -> list[Range]:
    """The run of consecutive kept ranges, at most `max_s` long, with the most
    speech in it. Without speech (scenery), the middle of the footage."""
    total = sum(b - a for a, b in ranges)
    if total <= max_s:
        return ranges
    best: list[Range] = []
    best_score = -1.0
    for i in range(len(ranges)):
        chosen: list[Range] = []
        length = 0.0
        for a, b in ranges[i:]:
            room = max_s - length
            if room <= 0:
                break
            piece = (a, min(b, a + room))
            chosen.append(piece)
            length += piece[1] - piece[0]
        if length < min(min_s, total):
            continue
        if speech:
            score = sum(_words_in(a, b, transcript) for a, b in chosen)
        else:
            # Prefer the window whose centre is nearest the footage's centre.
            mid_source = (ranges[0][0] + ranges[-1][1]) / 2
            mid_chosen = (chosen[0][0] + chosen[-1][1]) / 2
            score = -abs(mid_source - mid_chosen)
        if score > best_score:
            best, best_score = chosen, score
    return best or ranges


def remap(t: float, ranges: list[Range]) -> float | None:
    """Source time -> output time after `ranges` are concatenated."""
    offset = 0.0
    for a, b in ranges:
        if a <= t <= b:
            return round(offset + (t - a), 3)
        offset += b - a
    return None


def output_duration(ranges: list[Range]) -> float:
    return round(sum(b - a for a, b in ranges), 3)
