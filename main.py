from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from openai import OpenAI
import os, json, uuid, requests, re

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

# 네가 선택한 Taehyung Voice ID로 바꿔도 됨
DEFAULT_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

AUDIO_DIR = "audios"
SRT_DIR = "srts"
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(SRT_DIR, exist_ok=True)


class ShortsRequest(BaseModel):
    source_text: str
    tone: str = "초대형 라인업형"


class TTSRequest(BaseModel):
    text: str
    voice_id: str | None = None


class SRTRequest(BaseModel):
    captions: list[str]


@app.get("/")
def home():
    return {"message": "Shorts Maker AI API is running!"}


@app.post("/make-shorts")
def make_shorts(req: ShortsRequest):
    if not req.source_text.strip():
        raise HTTPException(status_code=400, detail="내용을 입력해주세요.")

    prompt = f"""
너는 한국 유튜브 쇼츠 전문 작가야.
특히 연예뉴스, 트로트, 팬덤형 쇼츠를 잘 만든다.

아래 원문을 바탕으로 유튜브 쇼츠 편집용 원고를 만들어줘.

출력 스타일은 반드시 이런 느낌이어야 한다:

🎬 숏츠 대본 (초대형 라인업형 🔥)

0~2초 (훅)
"전유진, 박서진, 홍지윤이 한자리에 모입니다."

2~6초
"현역가왕 역대 가왕들이
드디어 총출동하는데요"

조건:
- 시간대별 대본 필수
- 0~2초는 강한 훅
- 자막처럼 짧은 줄바꿈
- 댓글 유도 포함
- 제목 5개
- 추천 제목 1개
- 썸네일 문구 3개
- 조회수 포인트 5개
- 댓글 유도 2개
- 더 강한 조회수 버전 포함
- 원문에 없는 내용 과하게 지어내지 말 것
- 허위사실/루머처럼 단정하지 말 것

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
            model="gpt-4.1-nano",
            messages=[
                {"role": "system", "content": "너는 한국 유튜브 쇼츠 대본 제작 전문가다."},
                {"role": "user", "content": prompt},
            ],
            temperature=0.85,
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
