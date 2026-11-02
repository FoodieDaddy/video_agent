"""Deterministic text utilities: chapter splitting, names, locations."""

from __future__ import annotations

from pathlib import Path

from app.utils import narrative

SAMPLE = Path(__file__).resolve().parents[2] / "samples" / "novel_sample.txt"


def test_split_chapters_on_headings():
    text = "第一章 雨夜\n林简推开旧书店的门。\n\n第二章 清晨\n苏晚在柜台后等他。\n"

    chapters = narrative.split_chapters(text)

    assert [chapter["index"] for chapter in chapters] == [1, 2]
    assert chapters[0]["title"].startswith("第一章")
    assert "旧书店" in chapters[0]["content"]


def test_split_chapters_without_headings_chunks_document():
    chapters = narrative.split_chapters("没有标题的正文。" * 400, max_chars_per_chapter=200)

    assert chapters
    assert all(len(chapter["content"]) <= 200 for chapter in chapters)


def test_extract_character_names_from_sample():
    names = narrative.extract_character_names(SAMPLE.read_text(encoding="utf-8"))

    assert {"苏晚", "林简"} <= set(names)
    # Fragments such as "林简在" must not survive.
    assert all(2 <= len(name) <= 4 for name in names)


def test_extract_locations_is_deduplicated_and_clean():
    locations = narrative.extract_locations(SAMPLE.read_text(encoding="utf-8"))

    assert "旧书店" in locations
    # Greedy regex captures such as "苏晚关掉书店" have to be trimmed away.
    assert not any(character in name for name in locations for character in "关掉喊问")
    assert len(locations) == len(set(locations))


def test_dedupe_locations_keeps_the_longest_name():
    assert narrative.dedupe_locations(["书店", "旧书店", "门口"]) == ["旧书店", "门口"]


def test_estimate_speech_duration_scales_with_length():
    short = narrative.estimate_speech_duration("你好。")
    long = narrative.estimate_speech_duration("你好。" * 20)

    assert 0 < short < long
