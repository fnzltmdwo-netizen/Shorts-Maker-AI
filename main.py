from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from openai import OpenAI
import os
import json
import uuid
import requests
import re

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

    system_prompt = """
너는 대한민국 상위 0.1% 유튜브 쇼츠 작가다.

전문 분야:
- 연예뉴스
- 트로트
- 현역가왕
- 팬덤형 콘텐츠
- 화제성 콘텐츠

목표는 정보를 요약하는 것이 아니라 조회수가 터지는 쇼츠 원고를 만드는 것이다.

규칙:
- 첫 2초 훅이 가장 중요하다.
- 문장은 매우 짧게 쓴다.
- 뉴스 기사체 금지.
- 쇼츠 자막처럼 줄바꿈한다.
- 팬덤이 댓글을 달고 싶게 만든다.
- 원문에 없는 사실은 지어내지 않는다.
- 과장은 가능하지만 허위사실은 금지.
"""

    prompt = f"""
아래 기사를 보고 승재 채널 스타일의 쇼츠를 작성해줘.

반드시 아래 형식을 지켜.

🎬 숏츠 대본 (초대형 라인업형 🔥)

0~2초 (훅)
"짧고 강한 문장"

2~6초
"핵심 상황 설명"

6~11초
"사건 전개"

11~16초
"핵심 출연진 / 인물"

16~21초
"시청자 관심 포인트"

21~26초
"갈등 / 경쟁 / 비교"

26~31초 (댓글 유도)
"여러분 생각은?"

🔥 제목

1️⃣ 제목1
2️⃣ 제목2
3️⃣ 제목3
4️⃣ 제목4
5️⃣ 제목5

👉 추천 제목
"가장 잘 뽑힌 제목"

🖼 썸네일 문구

"문구1"
"문구2"
"문구3"

📈 조회수 포인트

✔ 포인트1
✔ 포인트2
✔ 포인트3
✔ 포인트4
✔ 포인트5

💬 댓글 유도

"댓글 문장1"
"댓글 문장2"

💣 더 강한 조회수 버전 (팬덤 싸움형)

0~2초
"결국 붙습니다."

2~7초
"더 자극적인 버전"

규칙:
- 쇼츠 길이 30~35초
- 첫 2초 무조건 강한 훅
- 문장 짧게
- 자막처럼 줄바꿈
- 딱딱한 뉴스체 금지
- 팬덤 댓글 유도
- 원문에 없는 사실 지어내지 말 것
- JSON 외 아무 말도 하지 말 것

기사:
{req.source_text}

아래 JSON 형식으로 출력:

{{
  "formatted_script": "",
  "captions": [],
  "titles": [],
  "recommended_title": "",
  "thumbnail_texts": [],
  "view_points": [],
  "comment_hooks": [],
  "strong_version": "",
  "tts_text": ""
}}
"""

    try:
        response = openai_client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=1.0,
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
