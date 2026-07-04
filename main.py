from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from openai import OpenAI
import os
import json
import uuid

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

AUDIO_DIR = "audios"
os.makedirs(AUDIO_DIR, exist_ok=True)


class ShortsRequest(BaseModel):
    source_text: str
    tone: str = "연예뉴스"
    length: str = "60초"
    style: str = "자극적이지만 선 넘지 않게"


class TTSRequest(BaseModel):
    text: str
    voice: str = "alloy"


@app.get("/")
def home():
    return {"message": "Shorts Maker AI API is running!"}


@app.post("/make-shorts")
def make_shorts(req: ShortsRequest):
    if not req.source_text.strip():
        raise HTTPException(status_code=400, detail="내용을 입력해주세요.")

    prompt = f"""
너는 유튜브 쇼츠 전문 작가야.

아래 원문을 바탕으로 유튜브 쇼츠용 콘텐츠를 만들어줘.

조건:
- 톤: {req.tone}
- 길이: {req.length}
- 스타일: {req.style}
- 한국어
- 초반 3초 훅 강하게
- 허위사실처럼 단정하지 말 것
- 명예훼손/악성 루머처럼 보이지 않게 표현
- 사람이 읽었을 때 자연스럽게
- TTS로 읽기 좋게 짧은 문장 위주

원문:
{req.source_text}

반드시 아래 JSON 형식으로만 답해줘.

{{
  "title": "쇼츠 제목",
  "hook": "첫 3초 훅",
  "script": "전체 쇼츠 대본",
  "captions": ["자막1", "자막2", "자막3"],
  "thumbnail_text": "썸네일 문구",
  "hashtags": ["#해시태그1", "#해시태그2"],
  "image_prompts": ["장면1 이미지 프롬프트", "장면2 이미지 프롬프트"]
}}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[
                {"role": "system", "content": "너는 유튜브 쇼츠 대본 제작 전문가다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.8
        )

        content = response.choices[0].message.content
        data = json.loads(content)
        return data

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI 생성 실패: {str(e)}")


@app.post("/make-tts")
def make_tts(req: TTSRequest):
    if not req.text.strip():
        raise HTTPException(status_code=400, detail="음성으로 만들 텍스트가 없습니다.")

    try:
        file_id = str(uuid.uuid4())
        file_path = os.path.join(AUDIO_DIR, f"{file_id}.mp3")

        with client.audio.speech.with_streaming_response.create(
            model="gpt-4o-mini-tts",
            voice=req.voice,
            input=req.text
        ) as response:
            response.stream_to_file(file_path)

        return {
            "audio_url": f"/audio/{file_id}.mp3"
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS 생성 실패: {str(e)}")


@app.get("/audio/{filename}")
def get_audio(filename: str):
    file_path = os.path.join(AUDIO_DIR, filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

    return FileResponse(file_path, media_type="audio/mpeg", filename=filename)
