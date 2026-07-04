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
import base64
import random

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
ALIGN_DIR = "alignments"
IMAGE_DIR = "images"
TEMP_DIR = "temp"

for d in [AUDIO_DIR, SRT_DIR, VIDEO_DIR, ALIGN_DIR, IMAGE_DIR, TEMP_DIR]:
    os.makedirs(d, exist_ok=True)


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
    alignment_url: str | None = ""
    images: list[str] = []


def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def format_srt_time(seconds: float) -> str:
    seconds = max(0, seconds)
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


def decode_base64_image(image_base64: str, save_path: str):
    if "," in image_base64:
        image_base64 = image_base64.split(",", 1)[1]

    image_base64 = image_base64.strip()
    image_bytes = base64.b64decode(image_base64)

    with open(save_path, "wb") as f:
        f.write(image_bytes)


def make_srt_from_alignment(alignment: dict, srt_path: str, max_len: int = 15):
    chars = alignment.get("characters", [])
    starts = alignment.get("character_start_times_seconds", [])
    ends = alignment.get("character_end_times_seconds", [])

    if not chars or not starts or not ends:
        raise Exception("alignment 데이터가 비어있습니다.")

    chunks = []
    cur_text = ""
    cur_start = None
    cur_end = None

    for ch, st, en in zip(chars, starts, ends):
        if cur_start is None and ch.strip():
            cur_start = st

        cur_text += ch
        cur_end = en

        should_cut = False

        if len(cur_text.strip()) >= max_len:
            should_cut = True

        if ch in [".", "!", "?", "…", "\n"]:
            should_cut = True

        if ch == " " and len(cur_text.strip()) >= 10:
            should_cut = True

        if should_cut and cur_text.strip():
            chunks.append({
                "text": cur_text.strip(),
                "start": cur_start if cur_start is not None else st,
                "end": cur_end,
            })
            cur_text = ""
            cur_start = None
            cur_end = None

    if cur_text.strip():
        chunks.append({
            "text": cur_text.strip(),
            "start": cur_start if cur_start is not None else 0,
            "end": cur_end if cur_end is not None else starts[-1],
        })

    srt = ""

    for i, c in enumerate(chunks, start=1):
        start = c["start"]
        end = max(c["end"], start + 0.35)

        srt += f"{i}\n"
        srt += f"{format_srt_time(start)} --> {format_srt_time(end)}\n"
        srt += f"{c['text']}\n\n"

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt)


def make_fallback_srt(tts_text: str, audio_duration: float, srt_path: str):
    text = clean_text(tts_text)
    words = text.split()
    chunks = []
    cur = ""

    for word in words:
        test = (cur + " " + word).strip()

        if len(test) <= 15:
            cur = test
        else:
            if cur:
                chunks.append(cur)
            cur = word

    if cur:
        chunks.append(cur)

    if not chunks:
        chunks = ["자막 생성 실패"]

    total = sum(len(c) for c in chunks)
    now = 0
    srt = ""

    for i, c in enumerate(chunks, start=1):
        dur = audio_duration * (len(c) / total)
        dur = max(dur, 0.8)

        start = now
        end = min(now + dur, audio_duration)

        if i == len(chunks):
            end = audio_duration

        srt += f"{i}\n"
        srt += f"{format_srt_time(start)} --> {format_srt_time(end)}\n"
        srt += f"{c}\n\n"

        now = end

    with open(srt_path, "w", encoding="utf-8") as f:
        f.write(srt)


def make_image_background_video(image_paths, duration, output_path):
    if not image_paths:
        raise Exception("업로드된 이미지가 없습니다.")

    segment_paths = []
    per_image_duration = duration / len(image_paths)

    effects = [
        "zoom_in",
        "zoom_out",
        "pan_left",
        "pan_right",
        "slow_push",
    ]

    for idx, img_path in enumerate(image_paths):
        segment_path = os.path.join(TEMP_DIR, f"{uuid.uuid4()}_seg.mp4")
        segment_paths.append(segment_path)

        frames = int(per_image_duration * 30)
        effect = effects[idx % len(effects)]

        if effect == "zoom_in":
            zoom_expr = "min(zoom+0.0018,1.18)"
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = "ih/2-(ih/zoom/2)"
        elif effect == "zoom_out":
            zoom_expr = "max(1.18-on*0.0018,1.0)"
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = "ih/2-(ih/zoom/2)"
        elif effect == "pan_left":
            zoom_expr = "1.12"
            x_expr = "(iw-iw/zoom)*(1-on/{frames})"
            y_expr = "ih/2-(ih/zoom/2)"
        elif effect == "pan_right":
            zoom_expr = "1.12"
            x_expr = "(iw-iw/zoom)*(on/{frames})"
            y_expr = "ih/2-(ih/zoom/2)"
        else:
            zoom_expr = "min(zoom+0.0012,1.12)"
            x_expr = "iw/2-(iw/zoom/2)"
            y_expr = "ih/2-(ih/zoom/2)"

        vf = (
            "scale=900:1600:force_original_aspect_ratio=increase,"
            "crop=900:1600,"
            f"zoompan=z='{zoom_expr}':"
            f"x='{x_expr}':"
            f"y='{y_expr}':"
            f"d={frames}:s=720x1280:fps=30,"
            "eq=contrast=1.06:brightness=0.02:saturation=1.08,"
            "vignette=PI/5"
        )

        cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            img_path,
            "-vf",
            vf,
            "-t",
            str(per_image_duration),
            "-r",
            "30",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            segment_path,
        ]

        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if result.returncode != 0:
            raise Exception(f"이미지 배경 세그먼트 생성 실패: {result.stderr}")

    concat_list_path = os.path.join(TEMP_DIR, f"{uuid.uuid4()}_concat.txt")

    with open(concat_list_path, "w", encoding="utf-8") as f:
        for p in segment_paths:
            f.write(f"file '{os.path.abspath(p).replace(chr(92), '/')}'\n")

    cmd_concat = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        concat_list_path,
        "-c",
        "copy",
        output_path,
    ]

    result = subprocess.run(
        cmd_concat,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if result.returncode != 0:
        raise Exception(f"이미지 배경 concat 실패: {result.stderr}")

    return output_path


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
- 첫 문장은 반드시 강한 후킹
- 연성 기사, 훈훈한 기사, 챌린지, 근황 기사라도 반드시 흥미로운 hook 생성
- 승재 스타일: 빠르고 자연스럽고 몰입감 있게
- 뉴스 말투 금지
- 허위 사실 금지
- 자막에 보기 좋게 짧은 문장
- 트로트/가수 기사에 맞게 팬들이 궁금해할 포인트를 살릴 것
- JSON만 출력

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
                {
                    "role": "system",
                    "content": "너는 한국 유튜브 쇼츠 대본 전문가다."
                },
                {
                    "role": "user",
                    "content": prompt
                },
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
    file_id = str(uuid.uuid4())

    audio_path = os.path.join(AUDIO_DIR, f"{file_id}.mp3")
    align_path = os.path.join(ALIGN_DIR, f"{file_id}.json")

    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/with-timestamps"

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
        r = requests.post(url, headers=headers, json=payload, timeout=180)
        r.raise_for_status()
        data = r.json()

        audio_base64 = data.get("audio_base64")
        alignment = data.get("alignment") or data.get("normalized_alignment")

        if not audio_base64:
            raise Exception("audio_base64가 없습니다.")

        if not alignment:
            raise Exception("alignment가 없습니다.")

        with open(audio_path, "wb") as f:
            f.write(base64.b64decode(audio_base64))

        with open(align_path, "w", encoding="utf-8") as f:
            json.dump(alignment, f, ensure_ascii=False)

        return {
            "voice_url": f"/audio/{file_id}.mp3",
            "alignment_url": f"/alignment/{file_id}.json",
            "tts_text": text,
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"음성 생성 실패: {str(e)}")


@app.post("/make-video")
def make_video(req: VideoRequest):
    try:
        voice_url = req.voice_url

        if voice_url.startswith("http"):
            audio_response = requests.get(voice_url, timeout=120)
            audio_response.raise_for_status()
            file_id = str(uuid.uuid4())
            audio_path = os.path.join(AUDIO_DIR, f"{file_id}.mp3")

            with open(audio_path, "wb") as f:
                f.write(audio_response.content)

            align_path = ""
        else:
            audio_filename = voice_url.split("/")[-1]
            file_id = audio_filename.replace(".mp3", "")
            audio_path = os.path.join(AUDIO_DIR, audio_filename)
            align_path = os.path.join(ALIGN_DIR, f"{file_id}.json")

        if req.alignment_url:
            align_filename = req.alignment_url.split("/")[-1]
            align_path = os.path.join(ALIGN_DIR, align_filename)

        if not os.path.exists(audio_path):
            raise HTTPException(status_code=404, detail="음성 파일을 찾을 수 없습니다.")

        video_id = str(uuid.uuid4())
        srt_path = os.path.join(SRT_DIR, f"{video_id}.srt")
        bg_video_path = os.path.join(TEMP_DIR, f"{video_id}_bg.mp4")
        output_path = os.path.join(VIDEO_DIR, f"{video_id}.mp4")

        audio_duration = get_audio_duration(audio_path)

        if align_path and os.path.exists(align_path):
            with open(align_path, "r", encoding="utf-8") as f:
                alignment = json.load(f)
            make_srt_from_alignment(alignment, srt_path, max_len=15)
        else:
            subtitle_text = clean_text(req.tts_text) or clean_text(req.script)
            make_fallback_srt(subtitle_text, audio_duration, srt_path)

        image_paths = []

        for img_b64 in req.images[:8]:
            img_path = os.path.join(IMAGE_DIR, f"{uuid.uuid4()}.jpg")
            decode_base64_image(img_b64, img_path)
            image_paths.append(img_path)

        if image_paths:
            make_image_background_video(image_paths, audio_duration, bg_video_path)
            video_input_args = ["-i", bg_video_path]
        else:
            video_input_args = [
                "-f",
                "lavfi",
                "-i",
                "color=c=black:s=720x1280:r=30"
            ]

        if not os.path.exists("NotoSansKR-Bold.ttf"):
            raise HTTPException(status_code=500, detail="NotoSansKR-Bold.ttf 폰트 파일이 없습니다.")

        safe_srt_path = srt_path.replace("\\", "/")

        vf = (
            f"subtitles='{safe_srt_path}':fontsdir='.'"
            f":force_style='"
            f"FontName=Noto Sans KR,"
            f"FontSize=24,"
            f"PrimaryColour=&H0000FFFF,"
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
            *video_input_args,
            "-i",
            audio_path,
            "-vf",
            vf,
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "27",
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
            raise HTTPException(status_code=500, detail=f"ffmpeg 영상 생성 실패: {result.stderr}")

        return {
            "video_url": f"/video/{video_id}.mp4",
            "srt_url": f"/srt/{video_id}.srt",
            "duration": audio_duration,
            "image_count": len(image_paths),
        }

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"영상 생성 실패: {str(e)}")


@app.get("/audio/{filename}")
def get_audio(filename: str):
    path = os.path.join(AUDIO_DIR, filename)

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="오디오 파일을 찾을 수 없습니다.")

    return FileResponse(path, media_type="audio/mpeg")


@app.get("/alignment/{filename}")
def get_alignment(filename: str):
    path = os.path.join(ALIGN_DIR, filename)

    if not os.path.exists(path):
        raise HTTPException(status_code=404, detail="alignment 파일을 찾을 수 없습니다.")

    return FileResponse(path, media_type="application/json")


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
