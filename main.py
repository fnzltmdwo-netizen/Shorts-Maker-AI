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
DEFAULT_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "EXAVITQu4vr4xnSDxMaL")

AUDIO_DIR = "audios"
SRT_DIR = "srts"
os.makedirs(AUDIO_DIR, exist_ok=True)
os.makedirs(SRT_DIR, exist_ok=True)


class ShortsRequest(BaseModel):
    source_text: str
    tone: str = "승재 쇼츠형"


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
너는 한국 유튜브 쇼츠 전문 작가다.
특히 연예뉴스, 트로트, 예능, 팬덤형 쇼츠를 잘 만든다.

목표는 '뉴스 요약'이 아니라,
사람들이 끝까지 보게 만드는 30초 쇼츠 대본 제작이다.

아래 원문을 바탕으로 쇼츠 편집용 원고를 만들어라.

[대본 스타일]
- 친구가 연예계 썰 풀어주는 느낌
- 기사체 금지
- 뉴스 앵커 말투 금지
- 문장은 짧게
- 한 구간당 1~2문장
- 자막처럼 줄바꿈
- "~는데요", "심지어", "근데", "하지만", "이유가 뭘까요?" 같은 쇼츠 말투 사용
- 원문에 없는 사실은 만들지 말 것
- 루머/열애/논란은 단정하지 말고 “전해졌습니다”, “눈길을 끌었습니다”, “해명했습니다”처럼 표현

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

[좋은 예시 1]
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
"자자연, 이수연, 솔지,
에녹, 전해성까지 초호화 라인업입니다"

21~26초
"센터 자리를 두고
치열한 맞대결도 펼쳐질 예정인데요"

26~31초 (댓글 유도)
"여러분이 생각하는 최종 1위는 누구인가요?"

[좋은 예시 2]
🎬 쇼츠 대본 (열애설 해명형 🔥)

0~2초 (훅)
"박서진, 홍지윤과 무슨 사이냐는 질문에 당황했습니다."

2~6초
"울릉도에서 주민들과 시간을 보내던 중
뜻밖의 질문이 나왔는데요"

6~10초
"한 주민이 홍지윤과 눈빛이 이상하던데
무슨 사이냐고 물었습니다"

10~14초
"심지어 출연진도 주변에서 많이 물어본다고 거들었는데요"

14~18초
"박서진은 곧바로
진짜 친구일 뿐이라며 선을 그었습니다"

18~23초
"하지만 주민들은 친구가 원래 여보가 되는 것이라며
웃음을 자아냈습니다"

23~28초 (댓글 유도)
"여러분은 박서진·홍지윤, 정말 친구라고 보시나요?"

[좋은 예시 3]
🎬 쇼츠 대본 (감동 실화형 🔥)

0~2초 (훅)
"에녹이 얼굴에 소금을 맞고 울었던 이유."

2~6초
"에녹은 20대부터
집안의 가장이었다고 밝혔는데요"

6~10초
"대학 졸업 무렵
아버지가 위암 말기 판정을 받았습니다"

10~14초
"생계를 위해 닥치는 대로
아르바이트를 하던 시절"

14~18초
"한 직원이 갑자기 얼굴에 소금을 뿌리며
재수 없다고 말했다는데요"

18~23초
"에녹은 골목에서 한참을 울었다고
가슴 아픈 과거를 털어놨습니다"

23~28초
"하지만 기적처럼
아버지는 16년째 건강을 유지 중이라고 합니다"

28~33초 (댓글 유도)
"에녹의 이야기,
여러분도 응원하시나요?"

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
                {
                    "role": "system",
                    "content": "너는 한국 유튜브 쇼츠 대본 제작 전문가다. JSON만 출력한다.",
                },
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
