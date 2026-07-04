from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import re

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ScriptRequest(BaseModel):
    script: str


@app.get("/")
def root():
    return {
        "message": "Shorts Maker AI v2 - Premiere Pack Edition",
        "status": "running",
    }


def time_to_seconds(text: str) -> float:
    text = text.strip().replace("초", "")

    if ":" in text:
        parts = text.split(":")
        if len(parts) == 2:
            minutes = int(parts[0])
            seconds = float(parts[1])
            return minutes * 60 + seconds

    return float(text)


def clean_caption_text(text: str) -> str:
    text = text.strip()
    text = text.replace('"', "")
    text = text.replace("“", "")
    text = text.replace("”", "")
    text = text.replace("'", "")
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
                        "text": clean_caption_text("\n".join(current_text_lines)),
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
                "text": clean_caption_text("\n".join(current_text_lines)),
            }
        )

    return blocks


@app.post("/parse-script")
def parse_script_api(request: ScriptRequest):
    if not request.script.strip():
        raise HTTPException(status_code=400, detail="대본이 비어있습니다.")

    blocks = parse_script(request.script)

    if not blocks:
        raise HTTPException(status_code=400, detail="시간 형식을 찾지 못했습니다.")

    return {
        "count": len(blocks),
        "blocks": blocks,
    }
