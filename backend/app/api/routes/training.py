"""Training dashboard — upload conversation screenshot + feedback → Claude rewrites prompts."""
import base64
import logging
import re
from pathlib import Path

import anthropic
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

from app.api.dashboard_auth import verify_dashboard_cookie, require_admin
from app.config import settings
from app.integrations.claude import MODEL

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/training", tags=["training"], dependencies=[Depends(require_admin)])

PROMPTS_FILE = Path("/app/app/prompts.py")

UPLOAD_DIR = Path("/app/uploads/training")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

TRAINER_PROMPT = """You are an AI prompt engineer improving an Indian Instagram seller bot.

The bot uses two main prompts stored in a Python file:
1. DECISION_PROMPT — decides what action to take (counter/hold_firm/accept/clarify etc.)
2. REPLY_PROMPT — generates the actual message text in Hinglish

A human reviewer has shared a conversation screenshot and feedback about what went wrong or right.

CURRENT PROMPTS FILE CONTENT:
{prompts_content}

REVIEWER FEEDBACK:
Type: {feedback_type}
What happened: {feedback_text}
{correct_response_section}

The conversation screenshot is attached. Analyze it carefully.

Your task:
1. Understand exactly what went wrong (or right) in the conversation
2. Identify which prompt(s) caused the issue
3. Rewrite ONLY the parts that need changing — keep everything else identical
4. Return the COMPLETE updated prompts.py file content, ready to be saved

Rules for your edits:
- Keep all Python syntax valid — this file will be saved and imported directly
- Keep all {{}} double-braces for format() placeholders — do NOT change them to single braces
- Do not add new prompt variables that aren't already used in the codebase
- Do not change IMAGE_DESCRIBE_PROMPT or CATALOG_MATCH_PROMPT unless the feedback is specifically about product image matching
- Make the minimum change that fixes the reported issue
- Return ONLY the complete file content, no explanation, no markdown fences
"""


@router.get("/dashboard")
async def training_dashboard():
    return FileResponse("/app/static/training.html")


@router.post("/feedback")
async def submit_feedback(
    feedback_type: str = Form(..., description="good or bad"),
    feedback_text: str = Form(..., description="What went wrong or right"),
    correct_response: str = Form(default="", description="What the bot should have said instead"),
    screenshot: UploadFile = File(...),
):
    """
    Accepts a conversation screenshot + feedback.
    Sends to Claude Vision to analyze and rewrite the prompts.
    Saves updated prompts.py — uvicorn auto-reloads.
    """
    if feedback_type not in ("good", "bad"):
        raise HTTPException(status_code=400, detail="feedback_type must be 'good' or 'bad'")

    # Read screenshot
    image_bytes = await screenshot.read()
    image_b64 = base64.b64encode(image_bytes).decode()
    media_type = _detect_media_type(image_bytes)

    # Save screenshot for audit trail
    ext = Path(screenshot.filename or "shot.jpg").suffix or ".jpg"
    import uuid as _uuid
    shot_path = UPLOAD_DIR / f"{_uuid.uuid4().hex}{ext}"
    shot_path.write_bytes(image_bytes)

    # Read current prompts
    prompts_content = PROMPTS_FILE.read_text(encoding="utf-8")

    correct_section = (
        f"What the bot should have said instead: {correct_response}"
        if correct_response.strip()
        else ""
    )

    prompt_text = TRAINER_PROMPT.format(
        prompts_content=prompts_content,
        feedback_type=feedback_type,
        feedback_text=feedback_text,
        correct_response_section=correct_section,
    )

    # Call Claude Vision
    client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
    response = await client.messages.create(
        model=MODEL,
        max_tokens=8000,
        messages=[{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt_text},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": media_type,
                        "data": image_b64,
                    },
                },
            ],
        }],
    )

    new_content = response.content[0].text.strip()

    # Safety check — must still be a valid Python file with our key prompts
    for required in ("DECISION_PROMPT", "REPLY_PROMPT", "IMAGE_DESCRIBE_PROMPT"):
        if required not in new_content:
            raise HTTPException(
                status_code=500,
                detail=f"Claude returned invalid prompts file — missing {required}. No changes saved.",
            )

    # Strip accidental markdown fences
    if new_content.startswith("```"):
        new_content = new_content.split("\n", 1)[-1]
        new_content = new_content.rsplit("```", 1)[0].strip()

    # Backup current prompts before overwriting
    backup = PROMPTS_FILE.with_suffix(".py.bak")
    backup.write_text(prompts_content, encoding="utf-8")

    # Save updated prompts — uvicorn --reload picks this up automatically
    PROMPTS_FILE.write_text(new_content, encoding="utf-8")
    logger.info("Prompts updated via training feedback (%s): %s", feedback_type, feedback_text[:80])

    # Also push the two hot-path prompts to the DB-backed prompt store so
    # worker/celery (which don't see uvicorn's hot-reload) pick them up
    # within the 60-second cache window.
    db_pushed: list[str] = []
    try:
        from app.bot import prompt_store
        from app.prompts import DECISION_PROMPT as _DECISION_PROMPT_NEW
        from app.prompts import REPLY_PROMPT as _REPLY_PROMPT_NEW
        import importlib
        import app.prompts as _prompts_module
        importlib.reload(_prompts_module)
        await prompt_store.upsert("decide", _prompts_module.DECISION_PROMPT)
        await prompt_store.upsert("generate_reply", _prompts_module.REPLY_PROMPT)
        db_pushed = ["decide", "generate_reply"]
    except Exception as exc:
        logger.warning("Failed to push updated prompts to DB store (%s) — file fallback still active", exc)

    return {
        "status": "updated",
        "feedback_type": feedback_type,
        "screenshot_saved": str(shot_path),
        "db_pushed": db_pushed,
        "message": "Prompts updated. Server will reload automatically in a few seconds.",
    }


@router.post("/revert")
async def revert_prompts():
    """Revert to the last backup if the update made things worse."""
    backup = PROMPTS_FILE.with_suffix(".py.bak")
    if not backup.exists():
        raise HTTPException(status_code=404, detail="No backup found")
    PROMPTS_FILE.write_text(backup.read_text(encoding="utf-8"), encoding="utf-8")
    logger.info("Prompts reverted to backup")
    return {"status": "reverted", "message": "Prompts restored from backup. Server reloading."}


def _detect_media_type(data: bytes) -> str:
    if data[:8] == b'\x89PNG\r\n\x1a\n':
        return "image/png"
    if data[:2] == b'\xff\xd8':
        return "image/jpeg"
    if data[:4] == b'RIFF' and data[8:12] == b'WEBP':
        return "image/webp"
    return "image/jpeg"
