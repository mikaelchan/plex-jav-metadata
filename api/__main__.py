"""
Plex JAV Metadata Provider — Plex Metadata Agent HTTP 服务
"""

import os
import re
import logging

from fastapi import FastAPI, HTTPException, Request, Body
from fastapi.responses import Response, PlainTextResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware

from api.scraper import scrape_number

logging.basicConfig(
    level=getattr(logging, os.environ.get("LOG_LEVEL", "INFO").upper()),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("plex_jav_provider")

VERSION = "1.0.0"
DATA_DIR = os.environ.get("DATA_DIR", "/data")
PROVIDER_ID = "tv.plex.agents.custom.jav-metadata"
PROVIDER_TITLE = "JAV Metadata"

app = FastAPI(title="Plex JAV Metadata Provider", version=VERSION)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# ══════════════════════════════════════════════════════════════
# 根端点
# ══════════════════════════════════════════════════════════════

@app.get("/")
async def root(request: Request):
    """Provider 声明"""
    accept = request.headers.get("accept", "*/*").lower()
    provider = {
        "MediaProvider": {
            "identifier": PROVIDER_ID,
            "title": PROVIDER_TITLE,
            "version": VERSION,
            "Types": [{
                "type": 1,
                "Scheme": [{"scheme": PROVIDER_ID}],
            }],
            "Feature": [
                {"type": "metadata", "key": "/metadata"},
                {"type": "match", "key": "/match"},
            ],
        }
    }
    if "xml" in accept or "*/*" in accept:
        return Response(content=_render_xml(provider["MediaProvider"]), media_type="application/xml")
    return provider


def _render_xml(provider: dict) -> str:
    types_parts = []
    for t in provider.get("Types", []):
        schemes = "".join(f"<Scheme>{s['scheme']}</Scheme>" for s in t.get("Scheme", []))
        types_parts.append(f'<Type type="{t["type"]}">{schemes}</Type>')
    types_xml = "".join(types_parts)
    features_parts = []
    for f in provider.get("Feature", []):
        features_parts.append(f'<Feature type="{f["type"]}" key="{f["key"]}"/>')
    features_xml = "".join(features_parts)
    i = provider['identifier']
    t = provider['title']
    v = provider.get('version', '')
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<MediaProvider>\n"
        f'  <Identifier>{i}</Identifier>\n'
        f'  <Title>{t}</Title>\n'
        f'  <Version>{v}</Version>\n'
        f'  {types_xml}\n'
        f'  {features_xml}\n'
        "</MediaProvider>"
    )


# ══════════════════════════════════════════════════════════════
# 元数据
# ══════════════════════════════════════════════════════════════

@app.get("/metadata/{rating_key}")
async def get_metadata(rating_key: str):
    number = rating_key.upper()
    result = scrape_number(number, DATA_DIR)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=f"Not found: {number}")
    return {
        "MediaContainer": {"offset": 0, "totalSize": 1, "identifier": PROVIDER_ID, "size": 1,
                           "Metadata": [_build_metadata(result)]}
    }


# ══════════════════════════════════════════════════════════════
# 搜索匹配
# ══════════════════════════════════════════════════════════════

@app.post("/match")
async def match(body: dict = Body(...)):
    """Plex 搜索匹配"""
    number = _extract_number(body.get("title", "")) \
             or _extract_number(body.get("filename", "")) \
             or _extract_number(body.get("guid", ""))

    if not number:
        return {"MediaContainer": {"offset": 0, "totalSize": 0, "size": 0, "Metadata": []}}

    result = scrape_number(number, DATA_DIR)
    if not result.get("success"):
        return {"MediaContainer": {"offset": 0, "totalSize": 0, "size": 0, "Metadata": []}}

    return {
        "MediaContainer": {"offset": 0, "totalSize": 1, "identifier": PROVIDER_ID, "size": 1,
                           "Metadata": [_build_metadata(result)]}
    }


# ══════════════════════════════════════════════════════════════
# 辅助
# ══════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    import importlib.util
    javsp_ok = importlib.util.find_spec("javsp") is not None
    return {"status": "ok", "version": VERSION, "provider": PROVIDER_ID,
            "engine": "javsp" if javsp_ok else "built-in"}


@app.get("/scrape/{number}")
async def scrape(number: str):
    result = scrape_number(number.upper(), DATA_DIR)
    if not result.get("success"):
        raise HTTPException(status_code=404, detail=result.get("error", "Not found"))
    return result


@app.get("/scrape/{number}/nfo")
async def scrape_nfo(number: str):
    result = scrape_number(number.upper(), DATA_DIR)
    if not result.get("nfo"):
        raise HTTPException(status_code=404)
    return PlainTextResponse(content=result["nfo"], media_type="application/xml",
                             headers={"Content-Disposition": f'attachment; filename="{result["nfo_filename"]}"'})


@app.get("/scrape/{number}/cover")
async def scrape_cover(number: str):
    result = scrape_number(number.upper(), DATA_DIR)
    if result.get("cover_bytes"):
        return Response(content=result["cover_bytes"], media_type="image/jpeg")
    if result.get("cover_url"):
        return RedirectResponse(url=result["cover_url"])
    raise HTTPException(status_code=404)


# ══════════════════════════════════════════════════════════════
# 番号提取
# ══════════════════════════════════════════════════════════════

def _extract_number(raw: str) -> str | None:
    """从 Plex 传过来的 title/filename/guid 中提取番号"""
    s = str(raw).strip().upper()
    if not s:
        return None

    # 空格转连接号后再匹配: ABW 005 -> ABW-005
    norm = re.sub(r"\s+", "-", s)
    m = re.search(r"([A-Za-z]{2,6}-?\d{2,7})", norm)
    if m:
        return m.group(1)

    # FC2 格式: FC2-1234567
    m = re.search(r"(FC2-\d{4,7})", s)
    if m:
        return m.group(1)

    # 1Pondo 格式: 010116 220 / 010116_220
    m = re.search(r"(\d{6})[ _](\d{2,3})", s)
    if m:
        return m.group(1) + "_" + m.group(2)

    # 纯6位数字（兜底）
    m = re.search(r"(\d{6})", s)
    if m:
        return m.group(1)

    return None


# ══════════════════════════════════════════════════════════════
# 元数据构建
# ══════════════════════════════════════════════════════════════

def _build_metadata(data: dict) -> dict:
    number = data.get("number", "")
    title = data.get("title") or number
    year = (data.get("release_date") or "0000")[:4]
    duration = int(data.get("runtime", 0)) * 60000 if data.get("runtime") else None

    meta = {
        "ratingKey": number,
        "key": f"/metadata/{number}",
        "guid": f"{PROVIDER_ID}://movie/{number}",
        "type": "movie",
        "title": title,
        "originalTitle": data.get("original_title") or number,
        "studio": data.get("studio") or "",
        "year": int(year) if year.isdigit() else None,
        "originallyAvailableAt": data.get("release_date"),
        "summary": data.get("plot") or "",
        "contentRating": "NC-17",
        "isAdult": True,
        "duration": duration,
        "thumb": data.get("cover_url") or "",
        "art": data.get("cover_url") or "",
    }

    genres = data.get("genre") or []
    if genres:
        meta["Genre"] = [{"tag": g} for g in genres]

    actresses = data.get("actress") or []
    if actresses:
        meta["Role"] = [{"tag": a} for a in actresses]

    return meta


if __name__ == "__main__":
    import uvicorn
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8800"))
    uvicorn.run("app.main:app", host=host, port=port)
