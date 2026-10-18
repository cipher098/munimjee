"""Native-only storefront design editor. Router mounting is an integration hook."""
from html import escape
from pathlib import Path
from uuid import UUID
from fastapi import APIRouter, Depends, Response
from fastapi.responses import FileResponse, HTMLResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.auth import enabled
from app.api.v1.identity import current_actor
from app.api.v1.session import business_mutation
from app.database import get_db
from app.schemas.storefront_theme_v1 import ThemeDraftWrite, ThemePublishWrite
from app.services import storefront_theme_v1 as domain
from app.services.identity import Actor

PRIVATE_HEADERS = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer", "X-Robots-Tag": "noindex, nofollow"}


def private(response: Response):
    response.headers.update(PRIVATE_HEADERS)


router = APIRouter(tags=["v1-theme-settings"], dependencies=[Depends(enabled), Depends(private)])
_STATIC = Path(__file__).resolve().parents[3] / "static"


@router.get("/v1/businesses/{business_id}/themes", include_in_schema=False)
async def workspace(business_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    await domain.authorize(db, actor, business_id)
    return FileResponse(_STATIC / "theme_settings.html", headers=PRIVATE_HEADERS)


@router.get("/api/v1/businesses/{business_id}/theme-settings")
async def read(business_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    return await domain.read_settings(db, actor, business_id)


@router.put("/api/v1/businesses/{business_id}/theme-settings")
async def save(business_id: UUID, body: ThemeDraftWrite, actor: Actor = Depends(business_mutation("business.write")), db: AsyncSession = Depends(get_db)):
    return await domain.apply_command(db, actor, business_id, body, "save")


@router.post("/api/v1/businesses/{business_id}/theme-settings/publish")
async def publish(business_id: UUID, body: ThemePublishWrite, actor: Actor = Depends(business_mutation("business.write")), db: AsyncSession = Depends(get_db)):
    return await domain.apply_command(db, actor, business_id, body, "publish")


_DEFAULTS = {
    "editorial": ("THE CELEBRATION EDIT", "For moments that stay.", "Occasionwear, considered.", "Pieces to make memories in."),
    "catalogue": ("EVERYDAY, ELEVATED", "Good pieces. Great repeats.", "Considered staples for your daily rotation.", "Your next everyday favourite."),
    "video": ("A CLOSER LOOK", "Made to move with you.", "Discover the pieces behind the story.", "From the story to your wardrobe."),
}


def preview_html(config, name):
    """Escaped design study only. No checkout JS/API or unpublished product data."""
    eyebrow, headline, intro, collection = _DEFAULTS[config["theme"]]
    text = lambda key, fallback="": escape(config[key] or fallback)
    palette = {"rose": ("#f9f2ef", "#9a514f"), "forest": ("#f4f5ee", "#365942"), "indigo": ("#f1f2f7", "#4f5689")}[config["palette"]]
    categories = '<nav aria-label="Illustrative categories">The collection · New arrivals</nav>' if config["show_categories"] else ""
    story = f'<section class="story"><h2>{text("story_heading", "Our story")}</h2><p>{text("story_body", "Add your boutique story in the design editor.")}</p></section>' if config["show_story"] else ""
    video = '<p class="film">Studio layout study · no seller video</p>' if config["theme"] == "video" else ""
    return f'''<!doctype html><html lang="en" data-theme="{config['theme']}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="robots" content="noindex,nofollow"><title>Private design preview</title><style>*{{box-sizing:border-box}}body{{margin:0;background:{palette[0]};color:#26382e;font:16px system-ui}}.notice{{padding:12px;background:#26382e;color:white;font-size:12px}}header{{padding:24px;border-bottom:1px solid #d9d9ce}}nav{{font-size:12px;margin-top:14px}}main{{max-width:1100px;margin:auto}}.hero{{display:grid;grid-template-columns:1fr 1fr;align-items:center;padding:40px;gap:35px}}h1{{font:clamp(32px,5vw,68px) Georgia;margin:16px 0;white-space:pre-line}}p{{line-height:1.7;white-space:pre-line;overflow-wrap:anywhere}}.eyebrow{{font-size:11px;letter-spacing:2px;color:{palette[1]}}}.art{{height:310px;background:linear-gradient(120deg,#dec3b4,#d3a698);border-radius:140px 140px 0 0}}[data-theme=catalogue] .art{{border-radius:5px;background:linear-gradient(120deg,#dedbbf,#b2c4a9)}}[data-theme=video] .art{{border-radius:5px;background:linear-gradient(120deg,#c3c7dd,#a89cbb)}}.film{{text-align:center;font-size:12px}}.collection,.story{{padding:25px 40px}}h2{{font:30px Georgia}}.pieces{{display:grid;grid-template-columns:repeat(3,1fr);gap:15px}}.piece{{min-height:150px;background:#e1d7cc}}.caption{{font-size:12px}}@media(max-width:600px){{.hero{{grid-template-columns:1fr;padding:24px}}.art{{height:230px}}.collection,.story{{padding:24px}}.pieces{{grid-template-columns:1fr 1fr}}}}</style></head><body><div class="notice">PRIVATE SAVED-DRAFT PREVIEW · checkout unavailable</div><header><strong>{escape(name)}</strong><p>{text('brand_tagline')}</p>{categories}</header><main><section class="hero"><div><span class="eyebrow">{text('hero_eyebrow', eyebrow)}</span><h1>{text('hero_headline', headline)}</h1><p>{text('hero_intro', intro)}</p></div><div><div class="art" role="img" aria-label="Illustrative layout placeholder"></div>{video}</div></section><section class="collection"><h2>{text('collection_heading', collection)}</h2><div class="pieces"><div class="piece"></div><div class="piece"></div><div class="piece"></div></div><p class="caption">Illustrative layout only. Product publication and availability are managed in Catalogue.</p></section>{story}</main></body></html>'''


@router.get("/api/v1/businesses/{business_id}/theme-settings/preview", response_class=HTMLResponse, include_in_schema=False)
async def preview(business_id: UUID, actor: Actor = Depends(current_actor), db: AsyncSession = Depends(get_db)):
    access = await domain.authorize(db, actor, business_id)
    data = await domain.read_settings(db, actor, business_id)
    return HTMLResponse(preview_html(data["draft"], access.business.name), headers={**PRIVATE_HEADERS,
        "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'self'; base-uri 'none'; form-action 'none'"})
