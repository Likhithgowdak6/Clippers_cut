"""Local video-frame analysis for shortlisted gameplay moments."""

import os
import re
import subprocess
from functools import lru_cache

import imageio_ffmpeg


MODEL_ID = "HuggingFaceTB/SmolVLM2-256M-Video-Instruct"


@lru_cache(maxsize=1)
def load_model():
    os.environ.setdefault("USE_TF", "0")
    import torch
    from transformers import AutoModelForImageTextToText, AutoProcessor

    model_id = os.environ.get("SHORTLIST_VISION_MODEL", MODEL_ID)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(min(4, os.cpu_count() or 1))
    processor = AutoProcessor.from_pretrained(model_id, use_fast=False)
    processor.image_processor.do_image_splitting = False
    processor.image_processor.size = {"longest_edge": 384}
    model = AutoModelForImageTextToText.from_pretrained(
        model_id, torch_dtype=torch.float16 if device == "cuda" else torch.float32,
        use_safetensors=True,
    ).to(device).eval()
    return torch, device, processor, model


def event_frames(start, end, event_time):
    duration = end - start
    center = duration / 2 if event_time is None else event_time - start
    center = max(0.5, min(duration - 0.5, center))
    last = max(0, int(duration * 2 - 1))
    return sorted({max(0, min(last, round(point * 2))) for point in
                   (.5, center - 1.5, center, center + 1.5, duration - 1)})


def sample_frames(source, start, end, event_time=None):
    from PIL import Image

    width, height = 384, 216
    frames = event_frames(start, end, event_time)
    select = "+".join(f"eq(n\\,{number})" for number in frames)
    raw = subprocess.run(
        [imageio_ffmpeg.get_ffmpeg_exe(), "-nostdin", "-v", "error", "-ss", str(start),
         "-i", str(source), "-t", str(end - start), "-map", "0:v:0",
         "-vf", f"fps=2,select={select},crop=iw*0.68:ih*0.76:(iw-ow)/2:(ih-oh)/2,scale={width}:{height}:"
                "force_original_aspect_ratio=decrease:force_divisible_by=2,"
                f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2",
         "-an", "-fps_mode", "vfr", "-frames:v", str(len(frames)), "-c:v", "rawvideo", "-threads", "1",
         "-pix_fmt", "rgb24", "-f", "rawvideo", "pipe:1"],
        check=True, capture_output=True, timeout=30,
    ).stdout
    stride = width * height * 3
    return [Image.frombytes("RGB", (width, height), raw[i:i + stride])
            for i in range(0, len(raw) - stride + 1, stride)]


def describe(source, start, end, event_time=None):
    torch, device, processor, model = load_model()
    frames = sample_frames(source, start, end, event_time)
    if not frames:
        return ""
    prompt = (
        "Describe the main game view across these frames in chronological order. Ignore the webcam and chat. "
        "Name the player's vehicle, the visible setting, and any clearly visible change in movement or nearby vehicles. "
        "Report ordinary movement if nothing changes. Use one short factual sentence."
    )
    content = [{"type": "image"} for _ in frames] + [{"type": "text", "text": prompt}]
    text = processor.apply_chat_template([{"role": "user", "content": content}], add_generation_prompt=True)
    inputs = processor(text=text, images=frames, return_tensors="pt").to(device)
    inputs["pixel_values"] = inputs["pixel_values"].to(model.dtype)
    with torch.inference_mode():
        output = model.generate(**inputs, do_sample=False, max_new_tokens=42)
    completion = output[:, inputs["input_ids"].shape[1]:]
    description = processor.batch_decode(completion, skip_special_tokens=True)[0]
    return " ".join(description.split())[:220]


VEHICLES = (
    (r"\b(?:motorcycle|motorbike|dirt bike|bike)\b", "motorcycle"),
    (r"\b(?:police van|police transport van)\b", "police van"),
    (r"\bvan\b", "van"),
    (r"\btruck\b", "truck"),
    (r"\b(?:car|sedan|suv|vehicle)\b", "car"),
)
SETTINGS = ("dirt road", "construction site", "bridge", "intersection", "parking lot", "highway", "tunnel")


def visual_headline(description, transcript=""):
    """Convert a narrow set of observations into titles and ranking adjustments."""
    text = description.lower()
    vehicle = next((name for pattern, name in VEHICLES if re.search(pattern, text)), "")
    setting = next((place for place in SETTINGS if re.search(rf"\b{place}\b", text)), "")
    bike = re.search(r"\b(?:bike|bicycle|motorbike|motorcycle)\b", text)
    car = re.search(r"\b(?:car|truck|van|sedan|suv|vehicle)\b", text)
    chase = re.search(r"\b(?:chas(?:e|es|ing)|pursu(?:it|es|ing))\b", text)
    jump = re.search(r"\b(?:jumps? (?:over|off|onto)|launches? (?:off|over)|goes airborne)\b", text)
    qualified = re.search(r"\b(?:no|not|never|without|doesn't|didn't|seems|appears|might|may|could)\b", text)
    near_crash = re.search(r"\b(?:almost|nearly) (?:crash(?:es)?|collid(?:e|es)|falls? off|hits?)\b", text)
    fall = re.search(r"\b(?:falls? off (?:the|his|her|their) (?:bike|motorcycle)|is thrown off)\b", text)
    spoken_close_call = re.search(r"\b(?:almost crashed|nearly crashed|near miss|almost fell|barely avoided)\b", transcript, re.I)
    spoken_fall = re.search(r"\b(?:fell off|got knocked off|was thrown off|came off the bike)\b", transcript, re.I)
    spoken_chase = re.search(r"\b(?:chase|chasing|pursuit|lose the cops|cops are after)\b", transcript, re.I)
    spoken_jump = re.search(r"\b(?:jumped|jumping|ramp|airborne|stunt)\b", transcript, re.I)
    location = f" {'through' if setting in {'intersection', 'tunnel'} else 'on'} the {setting}" if setting else ""
    if bike and near_crash and spoken_close_call and not qualified:
        return "The rider nearly wipes out", 1.4
    if bike and fall and spoken_fall and not qualified:
        return "The rider comes off the bike", 1.5
    if bike and chase and spoken_chase and not qualified:
        return "The bike chase is on", 1.2
    if bike and jump and spoken_jump and not qualified:
        return "The bike goes airborne", 1.2
    if car and chase and spoken_chase and not qualified:
        return (f"A police chase{location}" if "police" in text else f"A chase{location}"), 1.3
    if car and jump and spoken_jump and not qualified:
        return "The car goes airborne", 1.2
    if car and re.search(r"\b(?:turn(?:s|ing)|slid(?:es|ing)|skid(?:s|ding)|swing(?:s|ing)) sideways\b", text) and not qualified:
        return f"The {vehicle} turns sideways{location}", 1.0
    if car and re.search(r"\b(?:police (?:car|cruiser)|squad car)\b.{0,45}\b(?:follows|closes in|pulls alongside)\b", text) and not qualified:
        action = "pulls alongside" if "pulls alongside" in text else "closes in"
        proximity = f" at the {setting}" if setting in {"intersection", "parking lot"} else location
        return f"A police car {action}{proximity}", .9
    passing = re.search(r"\b(police van|police car|truck|van|car)\b.{0,24}\b(?:driving by|drives by|passes by)\b", text)
    if passing and not qualified:
        return f"A {passing[1]} passes{location}", .65
    if bike and re.search(r"\b(?:race|races|racing)\b", text):
        return "A moment from the bike race", 0.30
    if bike and re.search(r"\b(?:rid(?:es|ing)|driv(?:es|ing))\b", text):
        return ("Motorcycle ride on a dirt road" if "dirt road" in text else "On two wheels"), -0.15
    if car and re.search(r"\b(?:driv(?:es|ing)|rid(?:es|ing))\b", text):
        return (f"Driving through a construction site" if setting == "construction site"
                else f"The {vehicle} drives{location}" if setting else "Behind the wheel"), -.3
    if re.search(r"\b(?:standing still|stands still|sitting still|remains stationary)\b", text):
        return "", -.7
    return "", 0
