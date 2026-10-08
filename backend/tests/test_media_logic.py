"""The pure halves of the video pipeline: cutting, subtitles, glossary fixes."""

from growth_engine.media import edit_plan, glossary, subtitles
from growth_engine.media.ffmpeg import parse_silences
from growth_engine.media.render import plan_renders

TRANSCRIPT = {"segments": [
    {"start": 1.0, "end": 3.0, "text": "از قله‌ی شطری", "words": [
        {"start": 1.0, "end": 1.5, "word": "از"}, {"start": 1.5, "end": 2.2, "word": "قله‌ی"},
        {"start": 2.2, "end": 3.0, "word": "شطری"}]},
    {"start": 8.0, "end": 10.0, "text": "کویر تا افق پیداست", "words": [
        {"start": 8.0, "end": 8.6, "word": "کویر"}, {"start": 8.6, "end": 8.9, "word": "تا"},
        {"start": 8.9, "end": 9.4, "word": "افق"}, {"start": 9.4, "end": 10.0, "word": "پیداست"}]},
]}


def test_ffmpeg_silence_log_is_parsed_with_an_open_silence_at_the_end():
    log = "silence_start: 3.2\nsilence_end: 7.9 | silence_duration: 4.7\nsilence_start: 10.5\n"
    assert parse_silences(log, 12.0) == [(3.2, 7.9), (10.5, 12.0)]


def test_keep_ranges_drops_silences_and_the_shaky_edges():
    kept = edit_plan.keep_ranges(12.0, [(3.2, 7.9)])
    assert kept[0][0] == 0.5  # the first half second (pressing record) is cut
    assert kept[0][1] == 3.35 and kept[1][0] == 7.75  # padded so words are not clipped
    assert kept[-1][1] == 11.5


def test_choose_window_prefers_the_part_with_the_most_speech():
    ranges = [(0.0, 10.0), (20.0, 30.0), (40.0, 50.0)]
    transcript = {"segments": [{"start": 21, "end": 29, "text": "x",
                                "words": [{"start": 21 + i, "end": 21.5 + i, "word": "w"} for i in range(8)]}]}
    chosen = edit_plan.choose_window(ranges, transcript, min_s=10, max_s=15)
    assert chosen[0] == (20.0, 30.0)
    assert edit_plan.output_duration(chosen) <= 15


def test_scenery_without_speech_takes_the_middle():
    ranges = [(0.0, 10.0), (10.0, 20.0), (20.0, 30.0)]
    chosen = edit_plan.choose_window(ranges, None, min_s=5, max_s=10, speech=False)
    assert chosen == [(10.0, 20.0)]


def test_remap_moves_source_times_onto_the_cut_timeline():
    ranges = [(1.0, 3.0), (8.0, 10.0)]
    assert edit_plan.remap(8.5, ranges) == 2.5
    assert edit_plan.remap(5.0, ranges) is None  # cut away


def test_sentence_cues_follow_the_cut_and_break_on_pauses():
    cues = subtitles.build_cues(TRANSCRIPT, [(1.0, 3.0), (8.0, 10.0)], "sentence")
    assert [c.text for c in cues] == ["از قله‌ی شطری", "کویر تا افق پیداست"]
    assert cues[1].start == 2.0


def test_word_mode_makes_short_karaoke_chunks():
    cues = subtitles.build_cues(TRANSCRIPT, [(0.0, 12.0)], "word")
    assert all(len(c.words) <= subtitles.WORDS_PER_CHUNK for c in cues)
    ass = subtitles.build_ass(cues, width=1080, height=1920, font="Vazirmatn", text_color="#FFFFFF",
                              box_color="#1F2A44", highlight_color="#C9A66B", mode="word")
    assert "\\kf" in ass
    assert subtitles.RLM in ass  # right-to-left even when a line starts with a digit


def test_ass_colour_order_is_bgr():
    assert subtitles.ass_color("#112233") == "&H00332211"


def test_srt_format_matches_aparat_expectations():
    cues = subtitles.build_cues(TRANSCRIPT, [(0.0, 12.0)], "sentence")
    srt = subtitles.build_srt(cues)
    assert srt.startswith("1\n00:00:01,000 --> 00:00:03,000\nاز قله‌ی شطری")


def test_no_subtitles_when_the_recipe_says_none():
    assert subtitles.build_cues(TRANSCRIPT, [(0.0, 12.0)], "none") == []


def test_glossary_fixes_a_misheard_proper_name():
    assert glossary.correct_text("صعود قله‌ی شطری", ["شتری", "قلعه دختر"]) == "صعود قله‌ی شتری"


def test_glossary_normalises_arabic_letters_and_keeps_punctuation():
    assert glossary.correct_word("بشرويه،", ["بشرویه"]) == "بشرویه،"


def test_glossary_leaves_ordinary_words_alone():
    assert glossary.correct_text("هوا عالی بود", ["شتری"]) == "هوا عالی بود"


def test_explicit_fix_from_the_admin_wins():
    fixed = glossary.correct_transcript({"segments": [{"start": 0, "end": 1, "text": "ارسک", "words": []}]},
                                        [], {"ارسک": "ارسک‌کوه"})
    assert fixed["segments"][0]["text"] == "ارسک‌کوه"


def test_render_plan_has_short_story_and_full_versions():
    spec = {"min_s": 2, "max_s": 3, "aspects": ["9:16", "16:9"], "subtitle_mode": "word"}
    plans = {p.name: p for p in plan_renders(12.0, [(3.2, 7.9)], TRANSCRIPT, spec)}
    assert set(plans) == {"short", "story", "full"}
    assert edit_plan.output_duration(plans["short"].ranges) <= 3
    assert plans["full"].aspect == "16:9" and plans["full"].subtitle_mode == "sentence"


def test_render_plan_without_speech_has_no_subtitles():
    plans = plan_renders(20.0, [], None, {"min_s": 10, "max_s": 15, "aspects": ["9:16"], "subtitle_mode": "word"})
    assert all(p.cues == [] and p.subtitle_mode == "none" for p in plans)
    assert [p.name for p in plans] == ["short", "story"]


def test_every_style_lets_libass_detect_right_to_left():
    """Encoding 1 forced left-to-right: a Persian line came out with its words reversed."""
    ass = subtitles.build_ass([], width=1080, height=1920, font="Vazirmatn", text_color="#FFFFFF",
                              box_color="#000000", highlight_color="#FFFFFF", mode="sentence", overlay="عنوان")
    styles = [line for line in ass.splitlines() if line.startswith("Style:")]
    assert styles and all(line.endswith(",-1") for line in styles)
