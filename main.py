from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from openai import OpenAI
from PIL import Image, ImageDraw, ImageFont

import os, json, uuid, requests, re, textwrap, subprocess, shutil

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
너는 한국 유튜브 연예뉴스 쇼츠 전문 작가다.

중요:
이 작업은 단순 기사 요약이 아니다.
목표는 사람들이 스크롤을 멈추고 끝까지 보게 만드는 30초 쇼츠 대본 제작이다.

조회수가 잘 나오는 쇼츠의 핵심은:
1. 첫 2초 hook
2. 감정/반전
3. 댓글 유도

[핵심 스타일]
- 친구가 흥미로운 연예계 썰을 풀어주는 느낌
- 첫 2초 안에 반드시 시청자를 붙잡아야 한다
- 평범하게 시작하면 실패다
- 문장은 짧고 강하게
- 자막처럼 줄바꿈
- 감정, 반전, 궁금증 적극 활용

[말투 규칙]
- 너무 딱딱한 기사체 금지
- "~습니다"와 "~는데요"를 자연스럽게 섞어라
- "~했어요", "~나왔어요", "~보였어요", "~같아요" 금지
- 뉴스 앵커처럼 기계적으로 말하지 마라
- 연성 기사(훈훈함/챌린지/근황)라도 반드시 흥미로운 hook를 만들어라

[절대 금지]
절대로 아래처럼 시작하지 마라:
- OOO가 공개됐습니다
- OOO가 함께했습니다
- OOO가 출연했습니다
- OOO가 춤을 췄습니다
- OOO가 영상을 올렸습니다

[훅 규칙]
첫 문장은 반드시 아래 4개 중 하나:
1. 충격형
2. 반전형
3. 궁금증형
4. 감정형

[연성 기사 hook 예시]
- 팬들이 난리 난 이유가 있었습니다.
- 예상 못한 투샷이 공개됐습니다.
- 분위기가 심상치 않았습니다.
- 모두가 미소 지은 순간이었습니다.
- 뜻밖의 조합이 화제가 됐습니다.

[구성]
반드시 아래 형식:

🎬 쇼츠 대본 (유형명 🔥)

0~2초 (훅)

2~6초

6~10초

10~14초

14~18초

18~23초

23~28초 (댓글 유도)

[좋은 예시]

🎬 쇼츠 대본 (연성 기사형 🔥)

0~2초 (훅)
"팬들이 난리 난 이유가 있었습니다."

2~6초
"김다현과 전유진의
뜻밖의 투샷이 공개됐습니다"

6~10초
"두 사람은 챌린지 영상에서
완벽한 호흡을 보여줬습니다"

10~14초
"서로 다른 매력인데도
케미가 유독 빛났습니다"

14~18초
"특히 자연스러운 미소가
팬심을 제대로 흔들었습니다"

18~23초
"댓글에는 둘 조합 미쳤다는
반응이 쏟아졌습니다"

23~28초 (댓글 유도)
"여러분은 두 사람 케미 어떻게 보셨나요?"

[추가 출력]
- 제목 5개
- 추천 제목 1개
- 썸네일 문구 3개
- 조회수 포인트 5개
- 댓글 유도 2개
- strong_version은 hook를 더 강하게 재작성
- captions는 짧은 자막 6~8개
- tts_text는 음성용 텍스트

원문:
{req.source_text}

반드시 JSON만 출력.

{{
  "formatted_script": "전체 대본",
  "captions": ["자막1", "자막2"],
  "titles": ["제목1", "제목2", "제목3", "제목4", "제목5"],
  "recommended_title": "추천 제목",
  "thumbnail_texts": ["썸네일1", "썸네일2", "썸네일3"],
  "view_points": ["포인트1", "포인트2", "포인트3", "포인트4", "포인트5"],
  "comment_hooks": ["댓글1", "댓글2"],
  "strong_version": "강한 버전",
  "tts_text": "음성용 텍스트"
}}
"""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": "너는 한국 유튜브 쇼츠 대본 제작 전문가다. 반드시 JSON만 출력한다."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.82,
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


def get_font(size=84):
    try:
        return ImageFont.truetype("NotoSansKR-Bold.ttf", size)
    except:
        return ImageFont.load_default()


def make_caption_image(text, output_path):
    width, height = 720, 1280

    img = Image.new("RGB", (width, height), color=(25, 25, 25))
    draw = ImageDraw.Draw(img)

    font = get_font(84)

    clean_text = re.sub(r"\s+", " ", text).strip()
    wrapped = textwrap.fill(clean_text, width=8)

    bbox = draw.multiline_textbbox((0, 0), wrapped, font=font, spacing=20)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]

    x = (width - text_w) / 2
    y = (height - text_h) / 2

    draw.multiline_text(
        (x, y),
        wrapped,
        font=font,
        fill=(255, 230, 0),
        spacing=20,
        align="center",
        stroke_width=5,
        stroke_fill=(0, 0, 0),
    )

    img.save(output_path)


def get_audio_duration(audio_path):
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            audio_path,
        ]
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=20)
        return float(result.stdout.strip())
    except Exception:
        return 28.0


@app.post("/make-video")
def make_video(req: VideoRequest):
    if not req.audio_url:
        raise HTTPException(status_code=400, detail="audio_url이 없습니다.")

    if not req.captions:
        raise HTTPException(status_code=400, detail="captions가 없습니다.")

    if not shutil.which("ffmpeg"):
        raise HTTPException(status_code=500, detail="서버에 ffmpeg가 없습니다.")

    try:
        filename = req.audio_url.split("/")[-1]
        audio_path = os.path.join(AUDIO_DIR, filename)

        if not os.path.exists(audio_path):
            raise HTTPException(status_code=404, detail="음성 파일을 찾을 수 없습니다.")

        file_id = str(uuid.uuid4())
        work_dir = os.path.join(VIDEO_DIR, file_id)
        os.makedirs(work_dir, exist_ok=True)

        video_path = os.path.join(VIDEO_DIR, f"{file_id}.mp4")
        concat_path = os.path.join(work_dir, "concat.txt")

        audio_duration = get_audio_duration(audio_path)
        caption_duration = max(1.5, audio_duration / len(req.captions))

        image_paths = []

        for i, caption in enumerate(req.captions):
            img_path = os.path.join(work_dir, f"frame_{i}.png")
            make_caption_image(caption, img_path)
            image_paths.append(img_path)

        with open(concat_path, "w", encoding="utf-8") as f:
            for img_path in image_paths:
                f.write(f"file '{os.path.abspath(img_path)}'\n")
                f.write(f"duration {caption_duration}\n")
            f.write(f"file '{os.path.abspath(image_paths[-1])}'\n")

        cmd = [
            "ffmpeg",
            "-y",
            "-f", "concat",
            "-safe", "0",
            "-i", concat_path,
            "-i", audio_path,
            "-vf", "scale=720:1280,fps=24,format=yuv420p",
            "-c:v", "libx264",
            "-preset", "ultrafast",
            "-c:a", "aac",
            "-b:a", "128k",
            "-shortest",
            video_path,
        ]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=180,
        )

        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"ffmpeg 오류: {result.stderr[-1000:]}")

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
