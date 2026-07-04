from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from openai import OpenAI
import os
import uuid
import re
import json
import requests
import subprocess
import wave
import contextlib

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

openai_client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY")
DEFAULT_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

AUDIO_DIR = "audios"
SRT_DIR = "srts"
VIDEO_DIR = "videos"

os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(SRT_DIR, exist_ok=True)
os.makedirs(VIDEO_DIR, exist_ok=True)


class ScriptRequest(BaseModel):
    article: str


class VoiceRequest(BaseModel):
    text: str
    voice_id: str | None = None


class VideoRequest(BaseModel):
    title: str | None = ""
    script: str | None = ""
    tts_text: str | None = ""
    voice_url: str


def clean_text(text: str) -> str:
    text = text or ""
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def format_srt_time(seconds: float) -> str:
    millis = int((seconds - int(seconds)) * 1000)
    seconds = int(seconds)
    hrs = seconds // 3600
    mins = (seconds % 3600) // 60
    secs = seconds % 60
    return f"{hrs:02}:{mins:02}:{secs:02},{millis:03}"


def get_audio_duration(audio_path: str) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    try:
        return float(result.stdout.strip())
    except Exception:
        return 30.0


def split_subtitle_text(text: str, max_len: int = 16):
    text = clean_text(text)

    text = text.replace("!", "! ")
    text = text.replace("?", "? ")
    text = text.replace(".", ". ")
    text = text.replace("…", "… ")

    words = text.split()
    chunks = []
    current = ""

    for word in words:
        test = (current + " " + word).strip()

        if len(test) <= max_len:
            current = test
        else:
            if current:
                chunks.append(current)
            current = word

    if current:
        chunks.append(current)

    return chunks


def make_srt_from_tts_text(tts_text: str, audio_duration: float, srt_path: str):
    chunks = split_subtitle_text(tts_text, max_len=16)

    if not chunks:
        chunks = ["자막을 생성하지 못했습니다."]

    weights = []

    for chunk in chunks:
        weight = len(chunk)

        if chunk.endswith(("다", "요", "죠", "까", "!", "?", ".", "…")):
            weight += 5

        if "," in chunk or "，" in chunk:
            weight += 2

        weights.append(weight)

    total_weight = sum(weights)
    current_time = 0.0
    srt = ""

    for i, chunk in enumerate(chunks, start=1):
        duration = audio_duration * (weights[i - 1] / total_weight)

        duration = max(duration, 1.05)

        start = current_time
        end = min(start + duration, audio_duration)

        if i == len(chunks):
            end = audio_duration

        srt += f"{i}\n"
        srt += f"{format_srt_time(start)} --> {format_srt_time(end)}\n"
        srt += f"{chunk}\n\n"

        current_time = end

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt)


@app.get("/")
def root():
    return {
        "message": "Shorts Maker AI API is running!",
        "status": "ok"
    }


@app.post("/generate-script")
def generate_script(req: ScriptRequest):
    article = clean_text(req.article)

    if not article:
        raise HTTPException(status_code=400, detail="기사 내용이 비어있습니다.")

    prompt = f"""
너는 한국 유튜브 쇼츠 전문 작가다.

아래 기사 내용을 바탕으로 30~45초 분량의 쇼츠 대본을 만들어라.

규칙:
- 첫 문장은 반드시 강한 후킹으로 시작
- 연성 기사, 훈훈한 기사, 챌린지, 근황 기사라도 반드시 흥미로운 hook를 만들어라
- 말투는 자연스럽고 빠르게 몰입되는 승재 스타일
- 너무 딱딱한 뉴스 말투 금지
- 자막으로 보기 좋게 짧은 문장 사용
- 과장 가능하지만 허위 사실은 만들지 말 것
- 결과는 JSON으로만 출력

JSON 형식:
{{
  "title": "쇼츠 제목",
  "script": "화면에 보여줄 대본",
  "tts_text": "AI 음성으로 읽을 대본"
}}

기사:
{article}
"""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "너는 한국 유튜브 쇼츠 대본 전문가다."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.8,
        )

        content = response.choices[0].message.content.strip()

        content = content.replace("```json", "").replace("```", "").strip()
        data = json.loads(content)

        return {
            "title": data.get("title", ""),
            "script": data.get("script", ""),
            "tts_text": data.get("tts_text", data.get("script", "")),
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"대본 생성 실패: {str(e)}")


@app.post("/generate-voice")
def generate_voice(req: VoiceRequest):
    text = clean_text(req.text)

    if not text:
        raise HTTPException(status_code=400, detail="음성 생성용 텍스트가 비어있습니다.")

    if not ELEVENLABS_API_KEY:
        raise HTTPException(status_code=500, detail="ELEVENLABS_API_KEY가 없습니다.")

    voice_id = req.voice_id or DEFAULT_VOICE_ID
    filename = f"{uuid.uuid4()}.mp3"
    audio_path = os.path.join(AUDIO_DIR, filename)

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
    }

    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.45,
            "similarity_boost": 0.8,
            "style": 0.35,
            "use_speaker_boost": True,
        },
    }

    try:
        r = requests.post(url, headers=headers, json=payload, timeout=120)
        r.raise_for_status()

        with open(audio_path, "wb") as f:
            f.write(r.content)

        return {
            "voice_url": f"/audio/{filename}",
            "tts_text": text,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"음성 생성 실패: {str(e)}")


@app.get("/audio/{filename}")
def get_audio(filename: str):
    path = os.path.join(AUDIO_DIR, filename)

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="오디오 파일을 찾을 수 없습니다.")

    return FileResponse(path, media_type="audio/mpeg")


@app.post("/make-video")
def make_video(req: VideoRequest):
    try:
        voice_url = req.voice_url

        if voice_url.startswith("http"):
            audio_response = requests.get(voice_url, timeout=120)
            audio_response.raise_for_status()
            audio_filename = f"{uuid.uuid4()}.mp3"
            audio_path = os.path.join(AUDIO_DIR, audio_filename)

            with open(audio_path, "wb") as f:
                f.write(audio_response.content)
        else:
            audio_filename = voice_url.split("/")[-1]
            audio_path = os.path.join(AUDIO_DIR, audio_filename)

        if not os.path.exists(audio_path):
            raise HTTPException(status_code=404, detail="음성 파일을 찾을 수 없습니다.")

        video_id = str(uuid.uuid4())
        srt_path = os.path.join(SRT_DIR, f"{video_id}.srt")
        output_path = os.path.join(VIDEO_DIR, f"{video_id}.mp4")

        audio_duration = get_audio_duration(audio_path)

        subtitle_text = clean_text(req.tts_text) or clean_text(req.script)

        make_srt_from_tts_text(
            tts_text=subtitle_text,
            audio_duration=audio_duration,
            srt_path=srt_path,
        )

        font_path = "NotoSansKR-Bold.ttf"

        if not os.path.exists(font_path):
            raise HTTPException(status_code=500, detail="NotoSansKR-Bold.ttf 폰트 파일이 없습니다.")

        safe_srt_path = srt_path.replace("\\", "/")
        safe_font_path = font_path.replace("\\", "/")

        vf = (
            f"subtitles='{safe_srt_path}':"
            f"fontsdir='.'"
            f":force_style='"
            f"FontName=Noto Sans KR,"
            f"FontSize=22,"
            f"PrimaryColour=&H00FFFFFF,"
            f"OutlineColour=&H00000000,"
            f"BorderStyle=1,"
            f"Outline=3,"
            f"Shadow=1,"
            f"Alignment=2,"
            f"MarginV=130"
            f"'"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=720x1280:r=30",
            "-i",
            audio_path,
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "28",
            "-c:a",
            "aac",
            "-b:a",
            "128k",
            "-shortest",
            output_path,
        ]

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if result.returncode != 0:
            raise HTTPException(
                status_code=500,
                detail=f"ffmpeg 영상 생성 실패: {result.stderr}"
            )

        return {
            "video_url": f"/video/{video_id}.mp4",
            "srt_url": f"/srt/{video_id}.srt",
            "duration": audio_duration,
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"영상 생성 실패: {str(e)}")


@app.get("/video/{filename}")
def get_video(filename: str):
    path = os.path.join(VIDEO_DIR, filename)

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="영상 파일을 찾을 수 없습니다.")

    return FileResponse(path, media_type="video/mp4")


@app.get("/srt/{filename}")
def get_srt(filename: str):
    path = os.path.join(SRT_DIR, filename)

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="SRT 파일을 찾을 수 없습니다.")

    return FileResponse(path, media_type="text/plain")
