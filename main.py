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
        "message": "Shorts Maker AI v2 - Premiere Pack Edition",
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
    text = text.replace("'", "")
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


def create_srt(blocks, srt_path: Path):
    lines = []

    for index, block in enumerate(blocks, start=1):
        start = seconds_to_srt_time(block["start"])
        end = seconds_to_srt_time(block["end"])
        text = block["text"]

        lines.append(str(index))
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")

    srt_path.write_text("\n".join(lines), encoding="utf-8")


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


def create_guide_txt(blocks, guide_path: Path):
    lines = []
    lines.append("프리미어 작업 가이드")
    lines.append("")
    lines.append("1. mp3 파일을 1번부터 순서대로 A1 트랙에 배치")
    lines.append("2. subtitles.srt 파일을 프리미어 자막으로 가져오기")
    lines.append("3. 각 구간에 맞는 사진을 V1 트랙에 배치")
    lines.append("")
    lines.append("컷 구성")
    lines.append("")

    for index, block in enumerate(blocks, start=1):
        lines.append(f"컷 {index}: {block['start']}~{block['end']}초")
        lines.append(f"자막: {block['text']}")
        lines.append("추천 이미지: 관련 인물 사진 / 표정 클로즈업 / 방송 캡처")
        lines.append("")

    guide_path.write_text("\n".join(lines), encoding="utf-8")


@app.post("/parse-script")
def parse_script_api(request: ScriptRequest):
    if not request.script.strip():
        raise HTTPException(status_code=400, detail="대본이 비어있습니다.")

    blocks = parse_script(request.script)

    if not blocks:
        raise HTTPException(status_code=400, detail="시간 형식을 찾지 못했습니다.")

    return {
        "count": len(blocks),
        "blocks": blocks,
    }


@app.post("/generate-pack")
def generate_pack(request: ScriptRequest):
    if not request.script.strip():
        raise HTTPException(status_code=400, detail="대본이 비어있습니다.")

    blocks = parse_script(request.script)

    if not blocks:
        raise HTTPException(status_code=400, detail="시간 형식을 찾지 못했습니다.")

    job_id = str(uuid.uuid4())[:8]
    job_dir = OUTPUT_DIR / job_id
    job_dir.mkdir(exist_ok=True)

    for index, block in enumerate(blocks, start=1):
        mp3_path = job_dir / f"{index}.mp3"
        generate_elevenlabs_mp3(block["text"], mp3_path)

    create_srt(blocks, job_dir / "subtitles.srt")
    create_script_txt(blocks, job_dir / "script.txt")
    create_guide_txt(blocks, job_dir / "premiere_guide.txt")

    zip_path = OUTPUT_DIR / f"premiere_pack_{job_id}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file_path in job_dir.iterdir():
            zip_file.write(file_path, arcname=file_path.name)

    return FileResponse(
        path=zip_path,
        filename=f"premiere_pack_{job_id}.zip",
        media_type="application/zip",
    )
