from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
import os
import re
import uuid
import zipfile
import random
import requests
from pathlib import Path
from urllib.parse import quote_plus

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


TROT_PEOPLE = [
    {"name": "임영웅", "gender": "남자", "level": "HOT", "category": "미스터트롯"},
    {"name": "영탁", "gender": "남자", "level": "HOT", "category": "미스터트롯"},
    {"name": "이찬원", "gender": "남자", "level": "HOT", "category": "미스터트롯"},
    {"name": "김호중", "gender": "남자", "level": "HOT", "category": "미스터트롯"},
    {"name": "장민호", "gender": "남자", "level": "HOT", "category": "미스터트롯"},
    {"name": "정동원", "gender": "남자", "level": "HOT", "category": "미스터트롯"},
    {"name": "박서진", "gender": "남자", "level": "HOT", "category": "현역가왕"},
    {"name": "진해성", "gender": "남자", "level": "HOT", "category": "미스터트롯2"},
    {"name": "안성훈", "gender": "남자", "level": "HOT", "category": "미스터트롯2"},
    {"name": "박지현", "gender": "남자", "level": "HOT", "category": "미스터트롯2"},
    {"name": "나상도", "gender": "남자", "level": "숨은인물", "category": "미스터트롯2"},
    {"name": "최수호", "gender": "남자", "level": "숨은인물", "category": "미스터트롯2"},
    {"name": "진욱", "gender": "남자", "level": "숨은인물", "category": "미스터트롯2"},
    {"name": "에녹", "gender": "남자", "level": "HOT", "category": "불타는트롯맨"},
    {"name": "손태진", "gender": "남자", "level": "HOT", "category": "불타는트롯맨"},
    {"name": "신성", "gender": "남자", "level": "숨은인물", "category": "불타는트롯맨"},
    {"name": "민수현", "gender": "남자", "level": "숨은인물", "category": "불타는트롯맨"},
    {"name": "김중연", "gender": "남자", "level": "숨은인물", "category": "불타는트롯맨"},
    {"name": "공훈", "gender": "남자", "level": "숨은인물", "category": "불타는트롯맨"},
    {"name": "전종혁", "gender": "남자", "level": "숨은인물", "category": "불타는트롯맨"},

    {"name": "송가인", "gender": "여자", "level": "HOT", "category": "미스트롯"},
    {"name": "양지은", "gender": "여자", "level": "HOT", "category": "미스트롯2"},
    {"name": "홍지윤", "gender": "여자", "level": "HOT", "category": "미스트롯2"},
    {"name": "김다현", "gender": "여자", "level": "HOT", "category": "현역가왕"},
    {"name": "전유진", "gender": "여자", "level": "HOT", "category": "현역가왕"},
    {"name": "린", "gender": "여자", "level": "HOT", "category": "현역가왕"},
    {"name": "마이진", "gender": "여자", "level": "HOT", "category": "현역가왕"},
    {"name": "박혜신", "gender": "여자", "level": "HOT", "category": "현역가왕"},
    {"name": "마리아", "gender": "여자", "level": "숨은인물", "category": "미스트롯2"},
    {"name": "김태연", "gender": "여자", "level": "HOT", "category": "미스트롯2"},
    {"name": "은가은", "gender": "여자", "level": "HOT", "category": "미스트롯2"},
    {"name": "별사랑", "gender": "여자", "level": "숨은인물", "category": "미스트롯2"},
    {"name": "강혜연", "gender": "여자", "level": "숨은인물", "category": "미스트롯2"},
    {"name": "정다경", "gender": "여자", "level": "숨은인물", "category": "미스트롯"},
    {"name": "숙행", "gender": "여자", "level": "숨은인물", "category": "미스트롯"},
    {"name": "두리", "gender": "여자", "level": "숨은인물", "category": "미스트롯"},
    {"name": "김희진", "gender": "여자", "level": "숨은인물", "category": "미스트롯"},
    {"name": "강예슬", "gender": "여자", "level": "숨은인물", "category": "미스트롯"},
    {"name": "요요미", "gender": "여자", "level": "HOT", "category": "여성솔로"},
    {"name": "설하윤", "gender": "여자", "level": "HOT", "category": "여성솔로"},
    {"name": "지원이", "gender": "여자", "level": "숨은인물", "category": "여성솔로"},
    {"name": "오유진", "gender": "여자", "level": "HOT", "category": "미스트롯3"},
    {"name": "정서주", "gender": "여자", "level": "HOT", "category": "미스트롯3"},
    {"name": "배아현", "gender": "여자", "level": "HOT", "category": "미스트롯3"},
    {"name": "미스김", "gender": "여자", "level": "숨은인물", "category": "미스트롯3"},
    {"name": "나영", "gender": "여자", "level": "숨은인물", "category": "미스트롯3"},
    {"name": "김소연", "gender": "여자", "level": "숨은인물", "category": "미스트롯3"},
    {"name": "염유리", "gender": "여자", "level": "숨은인물", "category": "미스트롯3"},
]


@app.get("/")
def root():
    return {
        "message": "Shorts Maker AI v2",
        "status": "running",
        "trot_people_count": len(TROT_PEOPLE),
    }


def make_google_links(name: str):
    query = quote_plus(f"{name} 트로트")
    image_query = quote_plus(f"{name} 트로트 사진")

    return {
        "google_news_url": f"https://www.google.com/search?tbm=nws&q={query}",
        "google_image_url": f"https://www.google.com/search?tbm=isch&q={image_query}",
    }


def filter_people(gender: str = "전체", level: str = "전체"):
    people = TROT_PEOPLE

    if gender != "전체":
        people = [p for p in people if p["gender"] == gender]

    if level != "전체":
        people = [p for p in people if p["level"] == level]

    return people


@app.get("/random-trot-person")
def random_trot_person(
    gender: str = Query("전체"),
    level: str = Query("전체"),
):
    people = filter_people(gender, level)

    if not people:
        raise HTTPException(status_code=404, detail="조건에 맞는 인물이 없습니다.")

    person = random.choice(people)
    links = make_google_links(person["name"])

    return {
        "person": {
            **person,
            **links,
        },
        **links,
    }


@app.get("/random-trot-people")
def random_trot_people(
    count: int = Query(5, ge=1, le=20),
    gender: str = Query("전체"),
    level: str = Query("전체"),
):
    people = filter_people(gender, level)

    if not people:
        raise HTTPException(status_code=404, detail="조건에 맞는 인물이 없습니다.")

    picked = random.sample(people, min(count, len(people)))

    return {
        "count": len(picked),
        "people": [
            {
                **person,
                **make_google_links(person["name"]),
            }
            for person in picked
        ],
    }


def time_to_seconds(text: str) -> float:
    text = text.strip().replace("초", "")
    return float(text)


def clean_text(text: str) -> str:
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
                        "text": clean_text("\n".join(current_text_lines)),
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
                "text": clean_text("\n".join(current_text_lines)),
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

        lines.append(str(index))
        lines.append(f"{start} --> {end}")
        lines.append(block["text"])
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


def create_premiere_guide(blocks, guide_path: Path):
    lines = []
    lines.append("프리미어 작업 가이드")
    lines.append("")
    lines.append("1. 1.mp3, 2.mp3, 3.mp3 순서대로 A1 트랙에 배치")
    lines.append("2. 사진은 각 구간 길이에 맞게 V1 트랙에 배치")
    lines.append("3. 자막은 직접 프리미어 Essential Graphics에서 제작")
    lines.append("4. subtitles.srt는 참고용 기본 자막입니다")
    lines.append("")
    lines.append("컷별 구성")
    lines.append("")

    for index, block in enumerate(blocks, start=1):
        lines.append(f"{index}. {block['start']}~{block['end']}초")
        lines.append(f"음성 파일: {index}.mp3")
        lines.append(f"내용: {block['text']}")
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
    create_premiere_guide(blocks, job_dir / "premiere_guide.txt")

    zip_path = OUTPUT_DIR / f"audio_pack_{job_id}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file_path in job_dir.iterdir():
            zip_file.write(file_path, arcname=file_path.name)

    return FileResponse(
        path=zip_path,
        filename=f"audio_pack_{job_id}.zip",
        media_type="application/zip",
    )
