from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
import re
import uuid
import zipfile
import requests
from pathlib import Path

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)


class ScriptRequest(BaseModel):
    script: str


@app.get("/")
def root():
    return {
        "message": "Shorts Maker AI v2",
        "status": "running",
    }


def time_to_seconds(text: str) -> float:
    text = text.strip().replace("초", "")
    return float(text)


def clean_caption_text(text: str) -> str:
    text = text.strip()
    text = text.replace('"', "")
    text = text.replace("“", "")
    text = text.replace("”", "")
    text = re.sub(r"\n+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_script(script: str):
    lines = script.replace("\r", "\n").split("\n")

    blocks = []
    current_start = None
    current_end = None
    current_text_lines = []

    time_pattern = re.compile(
        r"(?P<start>\d+(?:\.\d+)?)\s*[~\-]\s*(?P<end>\d+(?:\.\d+)?)\s*초"
    )

    for line in lines:
        stripped = line.strip()

        if not stripped:
            continue

        match = time_pattern.search(stripped)

        if match:
            if current_start is not None and current_text_lines:
                blocks.append(
                    {
                        "start": current_start,
                        "end": current_end,
                        "text": clean_caption_text("\n".join(current_text_lines)),
                    }
                )

            current_start = time_to_seconds(match.group("start"))
            current_end = time_to_seconds(match.group("end"))
            current_text_lines = []
        else:
            if current_start is not None:
                if not stripped.startswith("🎬"):
                    current_text_lines.append(stripped)

    if current_start is not None and current_text_lines:
        blocks.append(
            {
                "start": current_start,
                "end": current_end,
                "text": clean_caption_text("\n".join(current_text_lines)),
            }
        )

    return blocks


def seconds_to_srt_time(seconds: float) -> str:
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    millis = int((seconds - int(seconds)) * 1000)

    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def split_big_caption(text: str) -> str:
    words = text.split()

    if not words:
        return text

    word_count = len(words)

    # 1단어
    if word_count == 1:
        chars = list(text)
        lines = []
        for i in range(0, len(chars), 6):
            lines.append("".join(chars[i:i + 6]))
        return "\n".join(lines[:4])

    # 2단어
    if word_count == 2:
        return "\n".join(words)

    # 3단어
    if word_count == 3:
        return "\n".join(words)

    # 4단어 ← 핵심
    if word_count == 4:
        return "\n".join([
            words[0],
            words[1] + " " + words[2],
            words[3]
        ])

    # 5단어
    if word_count == 5:
        return "\n".join([
            words[0] + " " + words[1],
            words[2] + " " + words[3],
            words[4]
        ])

    # 6개 이상
    lines = []
    chunk_size = max(2, round(word_count / 3))

    for i in range(0, word_count, chunk_size):
        chunk = words[i:i + chunk_size]
        lines.append(" ".join(chunk))

    return "\n".join(lines[:4])


def add_captions(blocks):
    new_blocks = []

    for block in blocks:
        copied = dict(block)
        copied["big_caption"] = split_big_caption(block["text"])
        new_blocks.append(copied)

    return new_blocks


def create_srt(blocks, srt_path: Path):
    lines = []

    for index, block in enumerate(blocks, start=1):
        start = seconds_to_srt_time(block["start"])
        end = seconds_to_srt_time(block["end"])
        text = block["big_caption"]

        lines.append(str(index))
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")

    srt_path.write_text("\n".join(lines), encoding="utf-8")


def create_big_caption_txt(blocks, txt_path: Path):
    lines = []

    for index, block in enumerate(blocks, start=1):
        lines.append(f"{index}.")
        lines.append(block["big_caption"])
        lines.append("")

    txt_path.write_text("\n".join(lines), encoding="utf-8")


def generate_elevenlabs_mp3(text: str, output_path: Path):
    if not ELEVENLABS_API_KEY:
        raise HTTPException(status_code=500, detail="ELEVENLABS_API_KEY가 없습니다.")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"

    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }

    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.85,
            "style": 0.35,
            "use_speaker_boost": True,
        },
    }

    response = requests.post(url, headers=headers, json=payload, timeout=120)

    if response.status_code != 200:
        raise HTTPException(
            status_code=500,
            detail=f"ElevenLabs 오류: {response.text}",
        )

    output_path.write_bytes(response.content)


def create_script_txt(blocks, txt_path: Path):
    lines = []

    for index, block in enumerate(blocks, start=1):
        lines.append(f"{index}. {block['start']}~{block['end']}초")
        lines.append(block["text"])
        lines.append("")

    txt_path.write_text("\n".join(lines), encoding="utf-8")


def create_caption_style_txt(style_path: Path):
    lines = [
        "폰트: 눈누 기초고딕 Bold",
        "크기: 280~340",
        "색상: 노란색",
        "정렬: 가운데",
        "Stroke: 검정 12~18",
        "Shadow: 검정 70%",
    ]

    style_path.write_text("\n".join(lines), encoding="utf-8")


@app.post("/parse-script")
def parse_script_api(request: ScriptRequest):
    blocks = parse_script(request.script)
    blocks = add_captions(blocks)

    return {
        "count": len(blocks),
        "blocks": blocks,
    }


@app.post("/generate-pack")
def generate_pack(request: ScriptRequest):
    blocks = parse_script(request.script)
    blocks = add_captions(blocks)

    job_id = str(uuid.uuid4())[:8]
    job_dir = OUTPUT_DIR / job_id
    job_dir.mkdir(exist_ok=True)

    for index, block in enumerate(blocks, start=1):
        mp3_path = job_dir / f"{index}.mp3"
        generate_elevenlabs_mp3(block["text"], mp3_path)

    create_srt(blocks, job_dir / "subtitles.srt")
    create_big_caption_txt(blocks, job_dir / "captions_big.txt")
    create_script_txt(blocks, job_dir / "script.txt")
    create_caption_style_txt(job_dir / "caption_style.txt")

    zip_path = OUTPUT_DIR / f"premiere_pack_{job_id}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file_path in job_dir.iterdir():
            zip_file.write(file_path, arcname=file_path.name)

    return FileResponse(
        path=zip_path,
        filename=f"premiere_pack_{job_id}.zip",
        media_type="application/zip",
    )
