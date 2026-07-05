from fastapi import FastAPI, HTTPException, Query, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from PIL import Image, ImageDraw, ImageFont
from openai import OpenAI
import os
import re
import uuid
import zipfile
import random
import requests
import csv
from pathlib import Path
from urllib.parse import quote_plus
from io import BytesIO

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

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_DIR = BASE_DIR / "outputs"
TROT_CSV_PATH = BASE_DIR / "trot_people.csv"

OUTPUT_DIR.mkdir(exist_ok=True)


class ScriptRequest(BaseModel):
    script: str
    title: str = "shorts_project"


class TitleRequest(BaseModel):
    article_title: str = ""
    article_body: str = ""
    person_name: str = ""
    tone: str = "자극적이지만 과장 없는 트로트 뉴스형"
    count: int = 5


def load_trot_people():
    people = []

    if not TROT_CSV_PATH.exists():
        return people

    with open(TROT_CSV_PATH, newline="", encoding="utf-8-sig") as csvfile:
        reader = csv.DictReader(csvfile)

        for row in reader:
            name = (row.get("name") or "").strip()

            if not name:
                continue

            people.append(
                {
                    "name": name,
                    "gender": (row.get("gender") or "기타").strip(),
                    "level": (row.get("level") or "숨은인물").strip(),
                    "category": (row.get("category") or "트로트").strip(),
                }
            )

    return people


TROT_PEOPLE = load_trot_people()


@app.get("/")
def root():
    return {
        "message": "Shorts Maker AI v6",
        "status": "running",
        "trot_people_count": len(TROT_PEOPLE),
        "csv_loaded": TROT_CSV_PATH.exists(),
        "openai_ready": bool(openai_client),
    }


def safe_filename(name: str) -> str:
    name = name.strip()

    if not name:
        return "shorts_project"

    name = re.sub(r"[^가-힣a-zA-Z0-9 _-]", "", name)
    name = re.sub(r"\s+", " ", name).strip()
    name = name[:30]

    if not name:
        return "shorts_project"

    return name


def zip_safe_filename(name: str) -> str:
    return safe_filename(name).replace(" ", "_")


def safe_upload_filename(filename: str) -> str:
    filename = Path(filename).name
    filename = re.sub(r'[\\/:*?"<>|]', "", filename)
    filename = filename.strip(" .")

    if not filename:
        filename = "image.jpg"

    return filename[:80]


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


def create_original_script_txt(original_script: str, txt_path: Path):
    txt_path.write_text(
        original_script.strip(),
        encoding="utf-8-sig",
    )


@app.post("/parse-script")
def parse_script_api(request: ScriptRequest):
    if not request.script.strip():
        raise HTTPException(status_code=400, detail="대본이 비어있습니다.")

    blocks = parse_script(request.script)

    if not blocks:
        raise HTTPException(status_code=400, detail="시간 형식을 찾지 못했습니다.")

    return {
        "title": safe_filename(request.title),
        "count": len(blocks),
        "blocks": blocks,
    }


@app.post("/generate-pack")
async def generate_pack(
    title: str = Form("shorts_project"),
    script: str = Form(...),
    images: list[UploadFile] = File(default=[]),
):
    if not script.strip():
        raise HTTPException(status_code=400, detail="대본이 비어있습니다.")

    title = safe_filename(title)
    zip_title = zip_safe_filename(title)

    blocks = parse_script(script)

    if not blocks:
        raise HTTPException(status_code=400, detail="시간 형식을 찾지 못했습니다.")

    job_id = str(uuid.uuid4())[:8]
    job_dir = OUTPUT_DIR / f"{zip_title}_{job_id}"
    project_dir = job_dir / title
    project_dir.mkdir(parents=True, exist_ok=True)

    create_original_script_txt(script, project_dir / "대본.txt")

    for index, block in enumerate(blocks, start=1):
        mp3_path = project_dir / f"{index}.mp3"
        generate_elevenlabs_mp3(block["text"], mp3_path)

    for index, image in enumerate(images, start=1):
        if not image.filename:
            continue

        original_name = safe_upload_filename(image.filename)
        ext = Path(original_name).suffix.lower()

        if ext not in [".jpg", ".jpeg", ".png", ".webp"]:
            ext = ".jpg"

        image_name = f"이미지{index:02d}_{Path(original_name).stem}{ext}"
        image_path = project_dir / image_name

        content = await image.read()
        image_path.write_bytes(content)

    zip_path = OUTPUT_DIR / f"{zip_title}_{job_id}.zip"

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for file_path in project_dir.iterdir():
            arcname = f"{title}/{file_path.name}"
            zip_file.write(file_path, arcname=arcname)

    return FileResponse(
        path=zip_path,
        filename=f"{zip_title}_{job_id}.zip",
        media_type="application/zip",
    )


def get_font(size: int):
    font_candidates = [
        BASE_DIR / "NotoSansKR-Bold.ttf",
        BASE_DIR / "NanumGothicBold.ttf",
        Path("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"),
    ]

    for font_path in font_candidates:
        if font_path.exists():
            return ImageFont.truetype(str(font_path), size)

    return ImageFont.load_default()


def cover_resize(image: Image.Image, target_width: int, target_height: int):
    image = image.convert("RGB")
    width, height = image.size

    scale = max(target_width / width, target_height / height)

    new_width = int(width * scale)
    new_height = int(height * scale)

    resized = image.resize((new_width, new_height), Image.LANCZOS)

    left = (new_width - target_width) // 2
    top = (new_height - target_height) // 2
    right = left + target_width
    bottom = top + target_height

    return resized.crop((left, top, right, bottom))


def wrap_thumbnail_text(text: str, max_chars: int = 7, max_lines: int = 4):
    text = re.sub(r"\s+", " ", text.strip())

    if not text:
        return [""]

    words = text.split(" ")
    lines = []
    current = ""

    for word in words:
        candidate = word if not current else current + " " + word

        if len(candidate.replace(" ", "")) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word

    if current:
        lines.append(current)

    if len(lines) > max_lines:
        compact = text.replace(" ", "")
        lines = [
            compact[i:i + max_chars]
            for i in range(0, len(compact), max_chars)
        ]

    return lines[:max_lines]


def fit_font(draw, lines, max_width, max_height, start_size, min_size, stroke_width):
    font_size = start_size

    while font_size >= min_size:
        font = get_font(font_size)
        max_line_width = 0
        total_height = 0

        for line in lines:
            bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
            line_width = bbox[2] - bbox[0]
            line_height = bbox[3] - bbox[1]
            max_line_width = max(max_line_width, line_width)
            total_height += line_height

        total_height += (len(lines) - 1) * 24

        if max_line_width <= max_width and total_height <= max_height:
            return font, font_size

        font_size -= 6

    return get_font(min_size), min_size


def draw_text_lines(
    draw,
    lines,
    font,
    center_x,
    start_y,
    fill,
    stroke_fill,
    stroke_width,
    line_gap,
):
    y = start_y

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=stroke_width)
        width = bbox[2] - bbox[0]
        height = bbox[3] - bbox[1]
        x = center_x - width // 2

        draw.text(
            (x, y),
            line,
            font=font,
            fill=fill,
            stroke_width=stroke_width,
            stroke_fill=stroke_fill,
        )

        y += height + line_gap


def draw_center_thumbnail(image: Image.Image, text: str):
    target_width = 1080
    target_height = 1920

    canvas = cover_resize(image, target_width, target_height)
    draw = ImageDraw.Draw(canvas, "RGBA")

    lines = wrap_thumbnail_text(text, max_chars=7, max_lines=4)
    font, _ = fit_font(
        draw=draw,
        lines=lines,
        max_width=960,
        max_height=760,
        start_size=150,
        min_size=70,
        stroke_width=10,
    )

    line_boxes = []
    max_line_width = 0

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font, stroke_width=10)
        line_width = bbox[2] - bbox[0]
        line_height = bbox[3] - bbox[1]
        max_line_width = max(max_line_width, line_width)
        line_boxes.append((line, line_width, line_height))

    total_height = sum(h for _, _, h in line_boxes) + (len(line_boxes) - 1) * 28

    box_padding_x = 50
    box_padding_y = 42

    box_width = min(1040, max_line_width + box_padding_x * 2)
    box_height = total_height + box_padding_y * 2

    box_left = (target_width - box_width) // 2
    box_top = (target_height - box_height) // 2
    box_right = box_left + box_width
    box_bottom = box_top + box_height

    draw.rounded_rectangle(
        (box_left, box_top, box_right, box_bottom),
        radius=34,
        fill=(0, 0, 0, 150),
    )

    y = box_top + box_padding_y

    for line, line_width, line_height in line_boxes:
        x = (target_width - line_width) // 2

        draw.text(
            (x, y),
            line,
            font=font,
            fill=(255, 221, 0, 255),
            stroke_width=10,
            stroke_fill=(0, 0, 0, 255),
        )

        y += line_height + 28

    return canvas


def draw_top_thumbnail(image: Image.Image, text: str):
    target_width = 1080
    target_height = 1920

    canvas = cover_resize(image, target_width, target_height)
    draw = ImageDraw.Draw(canvas, "RGBA")

    draw.rectangle((0, 0, target_width, 520), fill=(0, 0, 0, 105))

    lines = wrap_thumbnail_text(text, max_chars=9, max_lines=3)
    font, _ = fit_font(
        draw=draw,
        lines=lines,
        max_width=980,
        max_height=390,
        start_size=130,
        min_size=68,
        stroke_width=9,
    )

    draw_text_lines(
        draw=draw,
        lines=lines,
        font=font,
        center_x=target_width // 2,
        start_y=95,
        fill=(255, 255, 255, 255),
        stroke_fill=(80, 0, 120, 255),
        stroke_width=9,
        line_gap=24,
    )

    return canvas


def draw_bottom_thumbnail(image: Image.Image, text: str):
    target_width = 1080
    target_height = 1920

    canvas = cover_resize(image, target_width, target_height)
    draw = ImageDraw.Draw(canvas, "RGBA")

    draw.rectangle((0, 1350, target_width, target_height), fill=(0, 0, 0, 165))

    lines = wrap_thumbnail_text(text, max_chars=8, max_lines=3)
    font, _ = fit_font(
        draw=draw,
        lines=lines,
        max_width=980,
        max_height=420,
        start_size=145,
        min_size=72,
        stroke_width=10,
    )

    draw_text_lines(
        draw=draw,
        lines=lines,
        font=font,
        center_x=target_width // 2,
        start_y=1430,
        fill=(255, 225, 0, 255),
        stroke_fill=(0, 0, 0, 255),
        stroke_width=10,
        line_gap=26,
    )

    return canvas


def draw_thumbnail_by_template(image: Image.Image, text: str, template: str):
    if template == "top":
        return draw_top_thumbnail(image, text)

    if template == "bottom":
        return draw_bottom_thumbnail(image, text)

    return draw_center_thumbnail(image, text)


@app.post("/generate-thumbnail")
async def generate_thumbnail(
    title: str = Form("thumbnail"),
    thumbnail_text: str = Form(...),
    template: str = Form("center"),
    image: UploadFile = File(...),
):
    if not thumbnail_text.strip():
        raise HTTPException(status_code=400, detail="썸네일 문구가 비어있습니다.")

    if not image.filename:
        raise HTTPException(status_code=400, detail="이미지가 없습니다.")

    content = await image.read()

    try:
        source_image = Image.open(BytesIO(content)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=400, detail="이미지 파일을 열 수 없습니다.")

    safe_title = safe_filename(title)
    job_id = str(uuid.uuid4())[:8]

    thumbnail = draw_thumbnail_by_template(source_image, thumbnail_text, template)

    output_path = OUTPUT_DIR / f"thumbnail_{zip_safe_filename(safe_title)}_{job_id}.jpg"
    thumbnail.save(output_path, "JPEG", quality=95)

    return FileResponse(
        path=output_path,
        filename=f"thumbnail_{zip_safe_filename(safe_title)}.jpg",
        media_type="image/jpeg",
    )


@app.post("/generate-shorts-titles")
def generate_shorts_titles(request: TitleRequest):
    article_title = request.article_title.strip()
    article_body = request.article_body.strip()
    person_name = request.person_name.strip()
    tone = request.tone.strip()
    count = max(1, min(request.count, 5))

    if not article_title and not article_body:
        raise HTTPException(status_code=400, detail="기사 제목이나 본문이 비어있습니다.")

    if not openai_client:
        raise HTTPException(status_code=500, detail="OPENAI_API_KEY가 없습니다.")

    prompt = f"""
너는 한국 유튜브 쇼츠 트로트/연예 채널 제목 전문가다.

아래 기사 정보를 바탕으로 유튜브 쇼츠 제목 {count}개, 썸네일 문구 {count}개, 유튜브 설명 {count}개, 태그 10개를 만들어라.

조건:
- 제목은 15~35자 정도
- 허위 낚시 금지
- 기사 내용 안에서만 작성
- 분위기: {tone}
- 인물명: {person_name if person_name else "기사에서 추론"}
- 설명은 2~3줄로 짧게 작성
- 설명 마지막 줄에는 관련 해시태그를 자연스럽게 포함
- JSON 형식으로만 출력
- 코드블록 금지

출력 형식:
{{
  "titles": ["제목1", "제목2"],
  "thumbnail_texts": ["메인문구\\n강조문구", "메인문구\\n강조문구"],
  "tags": ["#태그1", "#태그2"]
}}

기사 제목:
{article_title}

기사 본문:
{article_body}
"""

    try:
        response = openai_client.responses.create(
            model="gpt-5-mini",
            input=prompt,
        )

        text = response.output_text.strip()
        text = text.replace("```json", "").replace("```", "").strip()

        import json
        data = json.loads(text)

        return {
            "titles": data.get("titles", []),
            "thumbnail_texts": data.get("thumbnail_texts", []),
            "descriptions": data.get("descriptions", []),
            "tags": data.get("tags", []),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
