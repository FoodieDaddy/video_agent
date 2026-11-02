"""Lightweight narrative utilities.

Two consumers:

* the novel parser (chapter/sentence segmentation), and
* the offline mock providers, so the whole pipeline can be exercised without any
  paid model credentials (development, CI and demos).

The heuristics are deliberately conservative: they must never invent text that is
not in the source, because downstream agents treat these snippets as evidence.
"""

from __future__ import annotations

import re
from collections import Counter

_CHAPTER_PATTERN = re.compile(
    r"^\s*(?:第\s*[0-9零一二三四五六七八九十百千万两]+\s*[章节回卷部篇]"
    r"|Chapter\s+\d+"
    r"|CHAPTER\s+\d+"
    r"|\d+[.、]\s*\S)"
)
_SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?；;…])|\n+")
_QUOTE_PATTERN = re.compile(r"[“\"「『]([^”\"」』]{1,200})[”\"」』]")
_ASCII_SPEECH = re.compile(
    r"([A-Z][a-zA-Z]{1,20})(?:\s+(?:said|asked|replied|whispered|shouted|cried))"
)
_LOCATION_AT = re.compile(
    r"在([\u4e00-\u9fa5]{2,10}?)(?:里|中|内|上|下|外|旁|边|之中|之间|门口|前面|后面|旁边)"
)
_LOCATION_MOVE = re.compile(
    r"(?:来到|走进|进入|回到|离开|抵达|前往|逃往|穿过|站在)([\u4e00-\u9fa5]{2,10})"
)

_NAME_STOPWORDS = {
    "他们",
    "她们",
    "我们",
    "你们",
    "大家",
    "众人",
    "有人",
    "一个",
    "自己",
    "对方",
    "这时",
    "此时",
    "然后",
    "于是",
    "但是",
    "如果",
    "因为",
    "所以",
    "这个",
    "那个",
    "什么",
    "多少",
    "这样",
    "那样",
    "一声",
    "一句",
    "两人",
    "三人",
    "门口",
    "心里",
    "心中",
    "眼中",
    "手中",
    "身后",
    "身上",
    "声音",
    "眼睛",
    "目光",
    "脸上",
    "一边",
    "终于",
    "忽然",
    "突然",
    "缓缓",
    "轻轻",
    # adverbs/adjectives that look like names when scanned out of context
    "低声",
    "轻声",
    "冷声",
    "沉声",
    "大声",
    "小声",
    "冷笑",
    "沉默",
    "淡淡",
    "冷冷",
    # place / object nouns frequently captured before a speech verb
    "屋子",
    "屋里",
    "房间",
    "院子",
    "楼上",
    "楼下",
    "大厅",
    "走廊",
    "窗户",
    "街道",
    "街上",
    "天空",
    "教室",
    "办公室",
    "车里",
    "山上",
    "河边",
    "shouted",
    "asked",
    "replied",
    "said",
}

_SPEECH_VERBS = "说|道|问|答|喊|叫|吼|叹|喃喃|嘀咕"
_SPEECH_ADVERBS = "轻声|低声|冷声|沉声|大声|小声|缓缓|冷冷地|淡淡地|笑着|苦笑"
_ACTION_CHARS = set("走站坐转抬低看望推拉握笑沉把将点摇伸退冲跑停来去说道问答喊叫吼叹的着了过在把被")
_FUNCTION_CHARS = set("没不要是也就都才又还只却让被把从向对和与在到很更最便即")
_PLACE_NOUNS = {
    "屋子",
    "屋里",
    "房间",
    "院子",
    "楼上",
    "楼下",
    "大厅",
    "走廊",
    "窗户",
    "街道",
    "街上",
    "天空",
    "教室",
    "办公室",
    "车里",
    "山上",
    "河边",
}


_LOCATION_STOPWORDS = {
    "这里",
    "那里",
    "哪里",
    "原地",
    "心里",
    "心中",
    "手里",
    "家中",
    "梦里",
    "身边",
    "身后",
    "面前",
    "眼前",
    "空中",
    "世上",
    "路上",
}

# Place nouns are recognised by suffix so "旧书店的门口" becomes "旧书店".
_PLACE_SUFFIXES = (
    "书店",
    "书铺",
    "咖啡馆",
    "酒吧",
    "餐厅",
    "旅馆",
    "酒店",
    "医院",
    "学校",
    "公司",
    "办公室",
    "教室",
    "大厅",
    "走廊",
    "门口",
    "院子",
    "屋子",
    "房间",
    "公寓",
    "车站",
    "机场",
    "码头",
    "街道",
    "广场",
    "公园",
    "店",
    "楼",
    "房",
    "屋",
    "院",
    "街",
    "巷",
    "桥",
    "山",
    "河",
)
_PLACE_NOUN = re.compile(
    r"([\u4e00-\u9fa5]{1,6}(?:" + "|".join(_PLACE_SUFFIXES) + r"))"
)
_LOCATION_VERBS = set("站走坐停看说想问拿推握转抬低望笑哭喊叫追跑回进出到过的了着把被让没不要是也就都才又还只在从向往")
_LOCATION_PRONOUNS = set("他她你我它您咱")

_EMOTION_KEYWORDS = {
    "怒": "愤怒",
    "笑": "微笑",
    "哭": "悲伤",
    "冷": "冷漠",
    "叹": "无奈",
    "怕": "恐惧",
    "急": "焦急",
    "惊": "惊讶",
}


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_chapters(text: str, title_hint: str = "", max_chars_per_chapter: int = 8000) -> list[dict]:
    """Split raw novel text into chapters using heading heuristics."""
    normalized = normalize_text(text)
    if not normalized:
        return []

    lines = normalized.split("\n")
    chapters: list[dict] = []
    current_title = title_hint or "第一章"
    buffer: list[str] = []
    seen_heading = False

    def flush() -> None:
        body = "\n".join(buffer).strip()
        if not body:
            return
        # Very long chapters are chunked so prompt sizes stay bounded.
        if len(body) > max_chars_per_chapter:
            for offset in range(0, len(body), max_chars_per_chapter):
                chunk = body[offset : offset + max_chars_per_chapter].strip()
                if chunk:
                    chapters.append(
                        {
                            "index": len(chapters) + 1,
                            "title": current_title if offset == 0 else f"{current_title}（续）",
                            "content": chunk,
                        }
                    )
        else:
            chapters.append(
                {"index": len(chapters) + 1, "title": current_title, "content": body}
            )

    for line in lines:
        stripped = line.strip()
        if stripped and len(stripped) <= 40 and _CHAPTER_PATTERN.match(stripped):
            seen_heading = True
            flush()
            buffer = []
            current_title = stripped
            continue
        if stripped:
            buffer.append(stripped)
        elif buffer:
            buffer.append("")

    flush()

    if not chapters:
        # No chapter headings at all: chunk the whole document.
        body = normalized
        for offset in range(0, len(body), max_chars_per_chapter):
            chunk = body[offset : offset + max_chars_per_chapter].strip()
            if chunk:
                chapters.append(
                    {
                        "index": len(chapters) + 1,
                        "title": f"{title_hint or '片段'} {len(chapters) + 1}",
                        "content": chunk,
                    }
                )
    if chapters and not seen_heading and not title_hint:
        chapters[0]["title"] = chapters[0]["title"] or "第一章"
    return chapters


def split_sentences(text: str) -> list[str]:
    parts = [part.strip() for part in _SENTENCE_SPLIT.split(text or "")]
    return [part for part in parts if part]


def summarize(text: str, max_chars: int = 180) -> str:
    sentences = split_sentences(text)
    summary = ""
    for sentence in sentences:
        if len(summary) + len(sentence) > max_chars and summary:
            break
        summary += sentence
    return summary[:max_chars].strip()


def _clean_name(name: str) -> str:
    name = re.sub(r"^(?:只见|这时|此时|随后|然后|接着)", "", name or "")
    return name.strip()


def _plausible_name(name: str) -> bool:
    """Reject tokens that are almost certainly not character names."""
    if not name or not (2 <= len(name) <= 4):
        return False
    if name in _NAME_STOPWORDS or name in _PLACE_NOUNS:
        return False
    if name[0] in "他她我你它这那其该":
        return False
    if name[-1] in "的了过在把被和与":
        return False
    if any(char in _FUNCTION_CHARS for char in name):
        return False
    return not any(char in _ACTION_CHARS for char in name)


_SENTENCE_START_ACTION = re.compile(
    r"^([\u4e00-\u9fa5]{2,3}?)(?:走|站|坐|转|抬|低|看|望|推|拉|握|笑|沉|点|摇|伸|退|冲|跑|停|从|向|把|将)"
)
_NAME_SPEECH = re.compile(
    rf"([\u4e00-\u9fa5]{{2,3}})(?:{_SPEECH_ADVERBS})?(?:{_SPEECH_VERBS})"
)
_NAME_COLON = re.compile(r"([\u4e00-\u9fa5]{2,3})\s*[：:]\s*[“\"「『]")


def extract_character_names(text: str, limit: int = 12) -> list[str]:
    """Rank probable character names with structural (not statistical) heuristics.

    Signals, strongest first:
    1. sentence-initial token followed by an action verb ("林简走进屋子");
    2. token directly followed by a speech verb, optionally an adverb ("苏晚低声道");
    3. token introducing a quote ("林简：……").

    Candidate tokens containing action/particle characters or common place nouns
    are rejected, which keeps "屋子，说" from being read as a person.
    """
    counter: Counter[str] = Counter()

    for sentence in split_sentences(text or ""):
        match = _SENTENCE_START_ACTION.match(sentence)
        if match:
            name = _clean_name(match.group(1))
            if _plausible_name(name):
                counter[name] += 3

    for match in _NAME_SPEECH.finditer(text or ""):
        name = _clean_name(match.group(1))
        if _plausible_name(name):
            counter[name] += 2

    for match in _NAME_COLON.finditer(text or ""):
        name = _clean_name(match.group(1))
        if _plausible_name(name):
            counter[name] += 1

    for match in _ASCII_SPEECH.finditer(text or ""):
        name = match.group(1)
        if name.lower() not in _NAME_STOPWORDS:
            counter[name] += 2

    return [name for name, _ in counter.most_common(limit)]


def extract_dialogues(
    text: str, chapter_index: int | None = None, known_names: list[str] | None = None
) -> list[dict]:
    """Extract ``“...”`` quotes and attribute them to the nearest speaker.

    When ``known_names`` is supplied the last mentioned known name before the quote
    wins, which is far more accurate than scanning for a verb and can never invent
    a speaker that does not exist in the story.
    """
    known = [name for name in (known_names or []) if name]
    dialogues: list[dict] = []
    for match in _QUOTE_PATTERN.finditer(text or ""):
        quote = match.group(1).strip()
        if len(quote) < 2:
            continue
        prefix = text[max(0, match.start() - 60) : match.start()]
        speaker = ""
        if known:
            # Chinese dialogue often names the speaker *after* the quote
            # (“你还敢回来。”苏晚低声说。), so the close suffix wins.
            suffix_head = text[match.end() : match.end() + 8].lstrip(" \t\r\n，。！？；、”」』")
            for name in known:
                if suffix_head.startswith(name):
                    speaker = name
                    break
        if not speaker and known:
            positions = [(prefix.rfind(name), name) for name in known if name in prefix]
            positions = [item for item in positions if item[0] >= 0]
            if positions:
                speaker = max(positions)[1]
        if not speaker and not known:
            verb_matches = list(_NAME_SPEECH.finditer(prefix))
            if verb_matches:
                candidate = _clean_name(verb_matches[-1].group(1))
                if _plausible_name(candidate):
                    speaker = candidate
        if not speaker:
            ascii_match = _ASCII_SPEECH.search(prefix)
            if ascii_match:
                speaker = ascii_match.group(1)
        if not speaker and known:
            speaker = known[0]
        if speaker in _NAME_STOPWORDS or len(speaker) > 8:
            speaker = ""
        emotion = ""
        for key, label in _EMOTION_KEYWORDS.items():
            if key in prefix[-8:]:
                emotion = label
                break
        dialogues.append(
            {
                "character_name": speaker or "未知",
                "text": quote,
                "emotion": emotion,
                "chapter_index": chapter_index,
            }
        )
    return dialogues


_LOCATION_BOUNDARY = _LOCATION_VERBS | _LOCATION_PRONOUNS | set(
    "的得了着过在和与把被让向从往对没不要是也就都才又还只却便即"
    "关开拿放抱扔捡翻听喊问答想念掉起撞踢打"
)


def _clean_location(name: str) -> str:
    """Cut subject/verb prefixes the regex greedily swallowed."""
    name = (name or "").strip()
    # "旧书店的门口" -> "旧书店": the head is the actual location.
    head_match = re.match(
        r"^(.{2,6}?)的(?:里面|里头|门口|对面|外面|旁边|边上|街上|里|中|内|上|下|旁|边)$",
        name,
    )
    if head_match:
        head = head_match.group(1)
        if head in _PLACE_NOUNS or head.endswith(_PLACE_SUFFIXES):
            return head
    cut = 0
    for index, char in enumerate(name[:-1]):
        if char in _LOCATION_BOUNDARY:
            cut = index + 1
    name = re.sub(r"^[的得了着过]+", "", name[cut:]).strip()
    # Trailing particles are only stripped when a real place noun remains.
    stripped = re.sub(
        r"(?:里面|里头|门口|对面|外面|旁边|边上|街上|里|中|内|上|下|旁|边)$", "", name
    )
    if len(stripped) >= 2 and (stripped in _PLACE_NOUNS or stripped.endswith(_PLACE_SUFFIXES)):
        name = stripped
    return name.strip("的 ")


def _looks_like_place(name: str) -> bool:
    if not (2 <= len(name) <= 8):
        return False
    if name in _LOCATION_STOPWORDS:
        return False
    if any(char in _LOCATION_PRONOUNS for char in name):
        return False
    if name in _PLACE_NOUNS:
        return True
    return name.endswith(_PLACE_SUFFIXES)


def extract_locations(text: str, limit: int = 8) -> list[str]:
    counter: Counter[str] = Counter()
    for pattern in (_LOCATION_AT, _LOCATION_MOVE, _PLACE_NOUN):
        for match in pattern.finditer(text or ""):
            name = _clean_location(match.group(1))
            if _looks_like_place(name):
                counter[name] += 1
    selected: list[str] = []
    for name, _ in counter.most_common(limit * 2):
        if any(name in chosen or chosen in name for chosen in selected):
            continue
        selected.append(name)
        if len(selected) >= limit:
            break
    return selected


def dedupe_locations(names: list[str]) -> list[str]:
    """Collapse overlapping place names, keeping the longest form.

    "书店" is a fragment of "旧书店", so only "旧书店" survives.
    """
    ordered = sorted({name for name in names if name}, key=len, reverse=True)
    selected: list[str] = []
    for name in ordered:
        if any(name in kept for kept in selected):
            continue
        selected.append(name)
    return selected


def emotion_from_context(context: str) -> str:
    for key, label in _EMOTION_KEYWORDS.items():
        if key in (context or ""):
            return label
    return "平静"


def estimate_speech_duration(text: str, chars_per_second: float = 5.0) -> float:
    length = len(text or "")
    return max(1.0, round(length / chars_per_second, 2))


def guess_gender(text: str) -> str:
    female = sum(1 for token in ("她", "姑娘", "女子", "少女", "母亲", "女孩") if token in (text or ""))
    male = sum(1 for token in ("他", "男子", "少年", "父亲", "男孩") if token in (text or ""))
    if female > male:
        return "female"
    if male > female:
        return "male"
    return "unknown"
