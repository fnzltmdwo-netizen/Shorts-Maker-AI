from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from openai import OpenAI
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

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

openai_client = OpenAI(api_key=OPENAI_API_KEY)

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
    millis = int(round((seconds - int(seconds)) * 1000))

    if millis >= 1000:
        millis = 0
        secs += 1

    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def fallback_big_caption(text: str) -> str:
    text = text.strip()

    if len(text) <= 8:
        return text

    words = text.split()
    lines = []
    current = ""

    for word in words:
        candidate = word if not current else current + " " + word

        if len(candidate.replace(" ", "")) <= 9:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    if 2 <= len(lines) <= 4:
        return "\n".join(lines)

    compact = text.replace(" ", "")
    lines = []

    for i in range(0, len(compact), 8):
        lines.append(compact[i:i + 8])

    return "\n".join(lines[:4])


def ai_big_caption(text: str) -> str:
    if not OPENAI_API_KEY:
        return fallback_big_caption(text)

    prompt = f"""
아래 문장을 유튜브 쇼츠용 큰 자막으로 줄바꿈해줘.

조건:
- 의미 단위로 자연스럽게 끊기
- 2~4줄
- 한 줄은 최대 9글자 정도
- 따옴표 금지
- 설명 금지
- 오직 줄바꿈된 자막만 출력

문장:
{text}
"""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {
                    "role": "system",
                    "content": "너는 한국 유튜브 쇼츠 자막 편집 전문가다.",
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.2,
        )

        caption = response.choices[0].message.content.strip()
        caption = caption.replace('"', "").replace("“", "").replace("”", "")
        caption = re.sub(r"\n{3,}", "\n", caption)

        lines = [line.strip() for line in caption.split("\n") if line.strip()]

        if not lines:
            return fallback_big_caption(text)

        if len(lines) > 4:
            return fallback_big_caption(text)

        return "\n".join(lines)

    except Exception:
        return fallback_big_caption(text)


def add_ai_captions(blocks):
    new_blocks = []

    for block in blocks:
        copied = dict(block)
        copied["big_caption"] = ai_big_caption(block["text"])
        new_blocks.append(copied)

    return new_blocks


def create_srt(blocks, srt_path: Path):
    lines = []

    for index, block in enumerate(blocks, start=1):
        start = seconds_to_srt_time(block["start"])
        end = seconds_to_srt_time(block["end"])
        text = block.get("big_caption") or fallback_big_caption(block["text"])

        lines.append(str(index))
        lines.append(f"{start} --> {end}")
        lines.append(text)
        lines.append("")

    srt_path.write_text("\n".join(lines), encoding="utf-8")


def create_big_caption_txt(blocks, txt_path: Path):
    lines = []

    for index, block in enumerate(blocks, start=1):
        lines.append(f"{index}.")
        lines.append(block.get("big_caption") or fallback_big_caption(block["text"]))
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
        lines.append(f"원문: {block['text']}")
        lines.append("큰자막:")
        lines.append(block.get("big_caption") or fallback_big_caption(block["text"]))
        lines.append("")

    txt_path.write_text("\n".join(lines), encoding="utf-8")


def create_caption_style_txt(style_path: Path):
    lines = [
        "프리미어 자막 스타일 추천",
        "",
        "폰트: 눈누 기초고딕 Bold / Pretendard ExtraBold / Noto Sans KR Black",
        "크기: 280~340",
        "색상: 노란색 #FFF200",
        "정렬: 가운데 정렬",
        "위치: 화면 정중앙",
        "Stroke: ON",
        "Stroke 색상: 검정",
        "Stroke 두께: 12~18",
        "Background: OFF 추천",
        "Shadow: ON",
        "Shadow 색상: 검정",
        "Shadow Opacity: 70~90%",
        "Shadow Blur: 0~5",
        "Shadow Distance: 6~10",
    ]

    style_path.write_text("\n".join(lines), encoding="utf-8")


def create_guide_txt(blocks, guide_path: Path):
    lines = []
    lines.append("프리미어 작업 가이드")
    lines.append("")
    lines.append("1. mp3 파일을 1번부터 순서대로 A1 트랙에 배치")
    lines.append("2. subtitles.srt 파일을 프리미어 자막으로 가져오기")
    lines.append("3. captions_big.txt를 참고해서 큰 자막 스타일 적용")
    lines.append("4. 각 구간에 맞는 사진을 V1 트랙에 배치")
    lines.append("")
    lines.append("컷 구성")
    lines.append("")

    for index, block in enumerate(blocks, start=1):
        lines.append(f"컷 {index}: {block['start']}~{block['end']}초")
        lines.append(f"원문: {block['text']}")
        lines.append("큰자막:")
        lines.append(block.get("big_caption") or fallback_big_caption(block["text"]))
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

    blocks = add_ai_captions(blocks)

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

    blocks = add_ai_captions(blocks)

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
