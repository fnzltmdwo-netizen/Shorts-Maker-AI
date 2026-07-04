from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from openai import OpenAI
import os, json, uuid

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
    tone: str = "초대형 라인업형"


class TTSRequest(BaseModel):
    text: str
    voice: str = "nova"


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

중요한 스타일:
- 시간대별로 나눠줘: 0~2초, 2~6초 이런 식
- 첫 문장은 강한 훅
- 문장은 짧게
- 실제 쇼츠 자막처럼 줄바꿈
- 팬덤 댓글 싸움이 생기게 질문 넣기
- 너무 루머처럼 단정하지 말기
- 조회수 포인트도 따로 정리
- 제목은 5개 만들고 추천 제목도 따로
- 썸네일 문구 3개
- 댓글 유도 문장 2개
- 더 강한 조회수 버전도 추가

원문:
{req.source_text}

반드시 아래 JSON 형식으로만 답해.

{{
  "main_title": "🎬 숏츠 대본 제목",
  "script_sections": [
    {{
      "time": "0~2초",
      "label": "훅",
      "text": "대사"
    }}
  ],
  "titles": ["제목1", "제목2", "제목3", "제목4", "제목5"],
  "recommended_title": "추천 제목",
  "thumbnail_texts": ["썸네일1", "썸네일2", "썸네일3"],
  "view_points": ["조회수 포인트1", "조회수 포인트2"],
  "comment_hooks": ["댓글유도1", "댓글유도2"],
  "strong_version": [
    {{
      "time": "0~2초",
      "text": "강한 버전 대사"
    }}
  ],
  "tts_text": "AI 음성으로 읽을 전체 대본"
}}
"""

    try:
        response = client.chat.completions.create(
            model="gpt-4.1-nano",
            messages=[
                {"role": "system", "content": "너는 유튜브 쇼츠 대본 제작 전문가다."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.9,
            response_format={"type": "json_object"}
        )

        return json.loads(response.choices[0].message.content)

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

        return {"audio_url": f"/audio/{file_id}.mp3"}

    except Exception as e:
        raise HTTPException(status_code=500, detail=f"TTS 생성 실패: {str(e)}")


@app.get("/audio/{filename}")
def get_audio(filename: str):
    file_path = os.path.join(AUDIO_DIR, filename)

    if not os.path.exists(file_path):
        raise HTTPException(status_code=404, detail="파일을 찾을 수 없습니다.")

    return FileResponse(file_path, media_type="audio/mpeg", filename=filename)
