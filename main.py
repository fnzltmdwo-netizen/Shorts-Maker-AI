from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont
from moviepy import ImageClip, AudioFileClip, concatenate_videoclips

import os, json, uuid, requests, re, textwrap

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


class ShortsRequest(BaseModel):
    source_text: str
    tone: str = "승재 쇼츠형"


class TTSRequest(BaseModel):
    text: str
    voice_id: str | None = None


class SRTRequest(BaseModel):
    captions: list[str]


class VideoRequest(BaseModel):
    audio_url: str
    captions: list[str]


@app.get("/")
def home():
    return {"message": "Shorts Maker AI API is running!"}


@app.post("/make-shorts")
def make_shorts(req: ShortsRequest):
    if not req.source_text.strip():
        raise HTTPException(status_code=400, detail="내용을 입력해주세요.")

    prompt = f"""
너는 한국 유튜브 쇼츠 전문 작가다.
특히 연예뉴스, 트로트, 예능, 팬덤형 쇼츠를 잘 만든다.

목표는 '뉴스 요약'이 아니라,
사람들이 끝까지 보게 만드는 30초 쇼츠 대본 제작이다.

[대본 스타일]
- 친구가 연예계 썰 풀어주는 느낌
- 기사체 금지
- 뉴스 앵커 말투 금지
- 문장은 짧게
- 한 구간당 1~2문장
- 자막처럼 줄바꿈
- "~는데요", "심지어", "근데", "하지만" 같은 쇼츠 말투 사용
- 원문에 없는 사실은 만들지 말 것
- 루머/논란은 단정하지 말 것

[반드시 이 형식]
🎬 쇼츠 대본 (유형명 🔥)

0~2초 (훅)
"강한 한 줄"

2~6초
"내용"

6~10초
"내용"

10~14초
"내용"

14~18초
"내용"

18~23초
"내용"

23~28초 (댓글 유도)
"댓글 유도 문장"

[좋은 예시]
🎬 쇼츠 대본 (초대형 라인업형 🔥)

0~2초 (훅)
"전유진, 박서진, 홍지윤이 한자리에 모입니다."

2~6초
"현역가왕 역대 가왕들이
드디어 총출동하는데요"

6~11초
"새 음악 예능
가왕쇼가 올 하반기 공개를 확정했습니다"

11~16초
"전유진, 박서진, 홍지윤이
MC를 맡고 각 시즌 TOP7까지 합류하는데요"

16~21초
"초호화 라인업이 공개되며
팬들의 기대가 커지고 있습니다"

21~26초
"센터 자리를 두고
치열한 맞대결도 펼쳐질 예정인데요"

26~31초 (댓글 유도)
"여러분이 생각하는 최종 1위는 누구인가요?"

[추가 출력물]
- 제목 5개
- 추천 제목 1개
- 썸네일 문구 3개
- 조회수 포인트 5개
- 댓글 유도 2개
- 더 강한 조회수 버전 1개
- tts_text는 따옴표, 시간표시 없이 자연스럽게 읽을 대본만 이어붙이기

원문:
{req.source_text}

반드시 JSON만 출력해.

{{
  "formatted_script": "시간대별 쇼츠 대본 전체",
  "captions": ["자막1", "자막2", "자막3"],
  "titles": ["제목1", "제목2", "제목3", "제목4", "제목5"],
  "recommended_title": "추천 제목",
  "thumbnail_texts": ["썸네일1", "썸네일2", "썸네일3"],
  "view_points": ["조회수포인트1", "조회수포인트2", "조회수포인트3", "조회수포인트4", "조회수포인트5"],
  "comment_hooks": ["댓글유도1", "댓글유도2"],
  "strong_version": "더 강한 조회수 버전 전체",
  "tts_text": "AI 음성으로 읽을 대본만 자연스럽게 이어붙인 텍스트"
}}
"""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "너는 한국 유튜브 쇼츠 대본 제작 전문가다. JSON만 출력한다."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.65,
            response_format={"type": "json_object"},
        )
        return json.loads(response.choices[0].message.content)

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 생성 실패: {str(e)}")


@app.post("/make-tts")
def make_tts(req: TTSRequest):
    if not ELEVENLABS_API_KEY:
        raise HTTPException(status_code=500, detail="ELEVENLABS_API_KEY가 없습니다.")

    if not req.text.strip():
        raise HTTPException(status_code=400, detail="음성으로 만들 텍스트가 없습니다.")

    try:
        voice_id = req.voice_id or DEFAULT_VOICE_ID
        file_id = str(uuid.uuid4())
        file_path = os.path.join(AUDIO_DIR, f"{file_id}.mp3")

        url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

        headers = {
            "xi-api-key": ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }

        payload = {
            "text": req.text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {
                "stability": 0.45,
                "similarity_boost": 0.8,
                "style": 0.35,
                "use_speaker_boost": True,
            },
        }

        r = requests.post(url, headers=headers, json=payload, timeout=90)

        if r.status_code != 200:
            raise HTTPException(status_code=500, detail=f"ElevenLabs 오류: {r.text}")

        with open(file_path, "wb") as f:
            f.write(r.content)

        return {"audio_url": f"/audio/{file_id}.mp3"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS 생성 실패: {str(e)}")


def srt_time(seconds: float):
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


@app.post("/make-srt")
def make_srt(req: SRTRequest):
    if not req.captions:
        raise HTTPException(status_code=400, detail="자막 데이터가 없습니다.")

    try:
        file_id = str(uuid.uuid4())
        file_path = os.path.join(SRT_DIR, f"{file_id}.srt")

        lines = []
        current = 0.0

        for i, caption in enumerate(req.captions, start=1):
            text = re.sub(r"\s+", " ", caption).strip()
            duration = max(2.0, min(4.0, len(text) * 0.12))
            start = current
            end = current + duration

            lines.append(str(i))
            lines.append(f"{srt_time(start)} --> {srt_time(end)}")
            lines.append(text)
            lines.append("")

            current = end

        with open(file_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        return {"srt_url": f"/srt/{file_id}.srt"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"SRT 생성 실패: {str(e)}")


def get_font(size=58):
    font_paths = [
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]

    for path in font_paths:
        if os.path.exists(path):
            return ImageFont.truetype(path, size)

    return ImageFont.load_default()


def make_caption_image(text, output_path):
    width, height = 1080, 1920
    img = Image.new("RGB", (width, height), color=(0, 0, 0))
    draw = ImageDraw.Draw(img)

    font = get_font(62)
    clean_text = re.sub(r"\s+", " ", text).strip()
    wrapped = textwrap.fill(clean_text, width=13)

    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=18)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x = (width - text_w) / 2
    y = (height - text_h) / 2

    draw.multiline_text(
        (x, y),
        wrapped,
        font=font,
        fill=(255, 255, 255),
        spacing=18,
        align="center",
    )

    img.save(output_path)


@app.post("/make-video")
def make_video(req: VideoRequest):
    if not req.audio_url:
        raise HTTPException(status_code=400, detail="audio_url이 없습니다.")

    if not req.captions:
        raise HTTPException(status_code=400, detail="captions가 없습니다.")

    try:
        filename = req.audio_url.split("/")[-1]
        audio_path = os.path.join(AUDIO_DIR, filename)

        if not os.path.exists(audio_path):
            raise HTTPException(status_code=404, detail="음성 파일을 찾을 수 없습니다.")

        file_id = str(uuid.uuid4())
        video_path = os.path.join(VIDEO_DIR, f"{file_id}.mp4")

        audio = AudioFileClip(audio_path)
        total_duration = audio.duration
        caption_duration = total_duration / len(req.captions)

        clips = []

        for i, caption in enumerate(req.captions):
            img_path = os.path.join(VIDEO_DIR, f"{file_id}_{i}.png")
            make_caption_image(caption, img_path)

            clip = ImageClip(img_path).set_duration(caption_duration)
            clips.append(clip)

        video = concatenate_videoclips(clips, method="compose")
        video = video.with_audio(audio)
        video = video.with_fps(24)

        video.write_videofile(
            video_path,
            codec="libx264",
            audio_codec="aac",
            fps=24,
            preset="ultrafast",
            threads=2,
            verbose=False,
            logger=None,
        )

        audio.close()
        video.close()

        return {"video_url": f"/video/{file_id}.mp4"}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"영상 생성 실패: {str(e)}")


@app.get("/audio/{filename}")
def get_audio(filename: str):
    file_path = os.path.join(AUDIO_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    return FileResponse(file_path, media_type="audio/mpeg", filename=filename)


@app.get("/srt/{filename}")
def get_srt(filename: str):
    file_path = os.path.join(SRT_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    return FileResponse(file_path, media_type="text/plain", filename=filename)


@app.get("/video/{filename}")
def get_video(filename: str):
    file_path = os.path.join(VIDEO_DIR, filename)
    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")
    return FileResponse(file_path, media_type="video/mp4", filename=filename)
