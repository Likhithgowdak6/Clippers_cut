import re
from dataclasses import dataclass


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    text: str
    words: tuple[tuple[float, float, str], ...] = ()


@dataclass(frozen=True)
class Clip:
    start: float
    end: float
    title: str
    reason: str
    segments: tuple[Segment, ...]
    hook: str = ""
    score: float = 0
    event_time: float | None = None
    hud: dict | None = None
    visual_event: bool = False


SENTENCE_END = (".", "!", "?", "。", "！", "？", "؟", "।", "॥")
STOP_WORDS = set("about after again also because before could does from have into just more most only over said same some than that their them then there these they this those very want what when where which with would your".split())


def topic_terms(text):
    return {word for word in re.findall(r"[^\W\d_]{4,}", text.casefold()) if word not in STOP_WORDS}


def rank_clips(segments, limit=5, max_duration=60):
    candidates = []
    ideal_duration = min(55, max_duration * .65)
    for first, segment in enumerate(segments):
        previous = segments[first - 1] if first else None
        clean_start = (previous is None or previous.text.endswith(SENTENCE_END)
                       or segment.start - previous.end >= .55)
        for last in range(first, len(segments)):
            end = segments[last]
            duration = end.end - segment.start
            if duration > max_duration:
                break
            if duration < 18:
                continue
            excerpt = tuple(segments[first:last + 1])
            opening = segment.text.lower()
            body = " ".join(part.text.lower() for part in excerpt)
            words = body.split()
            has_hook = bool(re.search(r"[?？؟]|\b(why|how|imagine|never|secret|mistake|believe|surprising)\b", opening))
            has_turn = bool(re.search(r"\b(but|turns out|because|instead|realized|until)\b", body))
            following = segments[last + 1] if last + 1 < len(segments) else None
            complete = end.text.endswith(SENTENCE_END) or (following is not None and following.start - end.end >= .7)
            dependent = bool(re.match(r"(and|so|but|yeah|right|then|it|they)\b", opening))
            density = min(len(words) / duration / 2.5, 1)
            score = (2.5 * has_hook + 2 * has_turn + 3 * complete + 2 * clean_start
                     - 3 * dependent + density - abs(ideal_duration - duration) / 24)
            title = " ".join(segment.text.split()[:9]).rstrip(".,:;")
            reason = (
                "The opening contains a question or a hook phrase." if has_hook else
                "The excerpt includes a contrast or explanation cue." if has_turn else
                "The excerpt ends at a transcript sentence boundary." if complete else
                "The excerpt has a relatively continuous stretch of speech."
            )
            candidates.append((score, Clip(segment.start, end.end, title, reason, excerpt), topic_terms(body)))
    selected = []
    topics = []
    for _, candidate, terms in sorted(candidates, key=lambda item: item[0], reverse=True):
        if any(min(clip.end, candidate.end) > max(clip.start, candidate.start) for clip in selected):
            continue
        if len(terms) >= 8 and any(len(terms & topic) / len(terms | topic) >= .72 for topic in topics):
            continue
        selected.append(candidate)
        topics.append(terms)
        if len(selected) == limit:
            break
    return selected


REACTION = re.compile(r"\b(?:no way|oh my (?:god|gosh)|what just happened|did you see that|let'?s go|are you kidding)\b", re.I)
ACTION = re.compile(r"\b(?:police chase|cops are|lose the cops|crashed|flipped|exploded|explosion|blew up|barely made it|near miss)\b", re.I)


def gameplay_headline(segments, reaction):
    speech = " ".join(segment.text for segment in segments).lower()
    rider = "Speed" if re.search(r"\b(?:ishowspeed|come on speed|speed (?:is|just|almost))\b", speech) else "The rider"
    bike = re.search(r"\b(?:bike|bikes|dirt bike|motorcycle|motorbike)\b", speech)
    race = re.search(r"\b(?:race|racing|lap|finish line)\b", speech)
    close_call = re.search(r"\b(?:almost crashed|nearly crashed|almost fell|near miss|barely made it)\b", speech)
    if bike and close_call:
        return f"{rider} nearly wipes out on the bike"
    if bike and race:
        return "The bike race gets wild" if reaction else "A tense moment in the bike race"
    if re.search(r"\b(?:police chase|cops are|lose the cops)\b", speech):
        return "The cops close in"
    if re.search(r"\b(?:crashed|flipped|exploded|blew up)\b", speech):
        return "Things go sideways fast"
    if close_call:
        return "That was way too close"
    return "Things get chaotic" if reaction else "The action picks up"


def rank_gameplay(segments, audio, motion, duration, *, sustained=()):
    candidates = []
    reaction_times = [
        ((segment.start + segment.end) / 2, segment)
        for segment in segments if REACTION.search(segment.text) or ACTION.search(segment.text)
    ]
    anchors = {round(time, 1) for time, _ in (*audio, *motion, *reaction_times)}
    for time in anchors:
        sound = max((value * (1 - 0.12 * abs(point - time))
                     for point, value in audio if abs(point - time) <= 3), default=0)
        movement = max((value * (1 - 0.12 * abs(point - time))
                        for point, value in motion if abs(point - time) <= 3), default=0)
        reactions = [segment for point, segment in reaction_times if abs(point - time) <= 5]
        action = next((segment for segment in reactions if ACTION.search(segment.text)), None)
        reaction = next((segment for segment in reactions if REACTION.search(segment.text)), None)
        signals = []
        if movement >= 0.30:
            signals.append("unusually fast visual change")
        if sound >= 0.16:
            signals.append("a burst of sound")
        if reaction:
            signals.append("a spoken reaction")
        if action and action is not reaction:
            signals.append("gameplay-related commentary")
        if len(signals) < 2 or not (movement >= 0.30 or action):
            continue
        start, end = max(0, time - 8), min(duration, time + 13)
        if end - start < 10:
            continue
        excerpt = tuple(segment for segment in segments if segment.end > start and segment.start < end)
        title = gameplay_headline(excerpt, reaction)
        score = 2.8 * movement + 1.7 * sound + 1.0 * bool(reaction) + 0.8 * bool(action)
        candidates.append(Clip(start, end, title, "Signals: " + ", ".join(signals) + ".", excerpt,
                               score=score, event_time=time))
    for time, strength in sustained:
        start, end = max(0, time - 8), min(duration, time + 13)
        if end - start < 10:
            continue
        excerpt = tuple(segment for segment in segments if segment.end > start and segment.start < end)
        candidates.append(Clip(start, end, "The pace picks up",
                               "Visual cue: motion stayed elevated after a quieter stretch.", excerpt,
                               score=2 + 2 * strength, event_time=time))
    selected = []
    for clip in sorted(candidates, key=lambda item: (-item.score, item.start)):
        if all(not same_gameplay_moment(clip, other) for other in selected):
            selected.append(clip)
    return selected[:5]


def same_gameplay_moment(left, right, left_offset=0, right_offset=0):
    overlap = min(left.end + left_offset, right.end + right_offset) - max(
        left.start + left_offset, right.start + right_offset
    )
    return overlap >= .45 * min(left.end - left.start, right.end - right.start)


def ass_time(seconds):
    total = round(max(seconds, 0) * 100)
    minutes, remainder = divmod(total, 6000)
    hours, minutes = divmod(minutes, 60)
    return f"{hours}:{minutes:02}:{remainder // 100:02}.{remainder % 100:02}"


def ass_text(value):
    return re.sub(r"[{}\\\r\n]", " ", value)


def caption_cues(clip):
    cues = []
    for segment in clip.segments:
        groups = [segment.words[i:i + 5] for i in range(0, len(segment.words), 5)]
        words = [(group[0][0], group[-1][1], "".join(word[2] for word in group).strip()) for group in groups]
        for start, end, phrase in words or [(segment.start, segment.end, segment.text)]:
            start = max(start, clip.start)
            end = min(end, clip.end)
            if end > start and phrase:
                cues.append((start, end, phrase))
    return cues


def captions(clip, width=1080, height=1920, style="bold", brand="", color="E3FF82"):
    scale = min(width, height) / 1080
    font_size = round((67 if style != "minimal" else 52) * scale)
    hook_color = color[4:6] + color[2:4] + color[0:2]
    primary = f"&H00{hook_color}" if style == "accent" else "&H00FFFFFF"
    lines = [
        "[Script Info]", "ScriptType: v4.00+", f"PlayResX: {width}", f"PlayResY: {height}",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,"
        "Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,"
        "Alignment,MarginL,MarginR,MarginV,Encoding",
        f"Style: Default,Arial,{font_size},{primary},&H00FFFFFF,&H00090909,&H96000000,"
        f"-1,0,0,0,100,100,0,0,1,5,1,2,{width//13},{width//13},{height*15//100},1",
        f"Style: Hook,Arial,{round(78*scale)},&H00{hook_color},&H00FFFFFF,&H00090909,&H96000000,"
        f"-1,0,0,0,100,100,0,0,1,6,1,8,{width//10},{width//10},{height//8},1",
        f"Style: Brand,Arial,{round(34*scale)},&H00{hook_color},&H00FFFFFF,&H00090909,&H96000000,"
        f"-1,0,0,0,100,100,0,0,1,3,0,9,32,32,{height//22},1",
        "[Events]", "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    if clip.hook:
        lines.append(f"Dialogue: 1,0:00:00.00,{ass_time(clip.end - clip.start)},Hook,,0,0,0,,{ass_text(clip.hook)}")
    if brand:
        lines.append(f"Dialogue: 2,0:00:00.00,{ass_time(clip.end - clip.start)},Brand,,0,0,0,,{ass_text(brand)}")
    for start, end, phrase in caption_cues(clip):
        lines.append(
            f"Dialogue: 0,{ass_time(start - clip.start)},{ass_time(end - clip.start)},"
            f"Default,,0,0,0,,{ass_text(phrase)}"
        )
    return "\n".join(lines) + "\n"
