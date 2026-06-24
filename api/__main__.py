"""
Plex JAV Metadata Provider — Plex Metadata Agent HTTP 服务

协议：
  GET  /              → MediaProvider 根声明
  GET  /metadata/{id} → Metadata 对象
  POST /match         → Match 搜索（JSON body）
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
    """Provider 声明。Plex 以此发现 provider 的 capabilities。"""
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
        return Response(
            content=_render_xml(provider["MediaProvider"]),
            media_type="application/xml",
        )
    return provider


def _render_xml(provider: dict) -> str:
    """将 MediaProvider 渲染为 Plex 兼容的 XML"""
    types_xml = ""
    for t in provider.get("Types", []):
        schemes = "".join(
            f"<Scheme>{s['scheme']}</Scheme>" for s in t.get("Scheme", [])
        )
        types_xml += f'<Type type="{t["type"]}">{schemes}</Type>'

    features_xml = "".join(
        f'<Feature type="{f["type"]}" key="{f["key"]}"/>'
        for f in provider.get("Feature", [])
    )

    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<MediaProvider>\n"
        f"  <Identifier>{provider['identifier']}</Identifier>\n"
        f"  <Title>{provider['title']}</Title>\n"
        f"  <Version>{provider.get('version', '')}</Version>\n"
        f"  {types_xml}\n"
        f"  {features_xml}\n"
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
        "MediaContainer": {
            "offset": 0, "totalSize": 1,
            "identifier": PROVIDER_ID, "size": 1,
            "Metadata": [_build_metadata(result)],
        }
    }


# ══════════════════════════════════════════════════════════════
# 搜索匹配
# ══════════════════════════════════════════════════════════════

@app.post("/match")
async def match(body: dict = Body(...)):
    """Plex 搜索匹配，POST JSON body"""
    title = body.get("title", "")
    filename = body.get("filename", "")
    guid = body.get("guid", "")

    # 从 title / filename / guid 中提取番号
    number = None
    for src in [title, filename, guid]:
        s = str(src).strip()
        if not s:
            continue
        # 标准番号: ABW-005, FC2-1234567
        m = re.search(r"([A-Za-z]{2,6}-?\d{2,7})", s.upper())
        if m:
            number = m.group(1)
            break
        # 纯数字番号（1Pondo 格式）: 010116, 010116_220
        # 1Pondo 格式: 010116 220 或 010116_220
        m = re.search(r"(\d{6})[ _](\d{2,3})", s)
        if m:
            number = m.group(1) + "_" + m.group(2)
            break
        # 也尝试纯6位数字
        m = re.search(r"(\d{6})", s)
        if m:
            number = m.group(1)
            break

    if not number:
        return {"MediaContainer": {"offset": 0, "totalSize": 0, "size": 0, "Metadata": []}}

    result = scrape_number(number, DATA_DIR)
    if not result.get("success"):
        return {"MediaContainer": {"offset": 0, "totalSize": 0, "size": 0, "Metadata": []}}

    return {
        "MediaContainer": {
            "offset": 0, "totalSize": 1,
            "identifier": PROVIDER_ID, "size": 1,
            "Metadata": [_build_metadata(result)],
        }
    }


# ══════════════════════════════════════════════════════════════
# 手动刮削端点
# ══════════════════════════════════════════════════════════════

@app.get("/health")
async def health():
    import importlib.util
    javsp_ok = importlib.util.find_spec("javsp") is not None
    return {
        "status": "ok", "version": VERSION,
        "provider": PROVIDER_ID,
        "engine": "javsp" if javsp_ok else "built-in",
    }


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
    return PlainTextResponse(
        content=result["nfo"], media_type="application/xml",
        headers={"Content-Disposition": f'attachment; filename="{result["nfo_filename"]}"'},
    )


@app.get("/scrape/{number}/cover")
async def scrape_cover(number: str):
    result = scrape_number(number.upper(), DATA_DIR)
    if result.get("cover_bytes"):
        return Response(content=result["cover_bytes"], media_type="image/jpeg")
    if result.get("cover_url"):
        return RedirectResponse(url=result["cover_url"])
    raise HTTPException(status_code=404)


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
