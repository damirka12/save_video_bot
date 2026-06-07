"""Веб-админка для редактирования всех текстов бота.

Запуск:  uvicorn web.app:app --host 0.0.0.0 --port 8080
Доступ под Basic-Auth (логин/пароль из .env: ADMIN_PANEL_USER / ADMIN_PANEL_PASSWORD).
Тексты сохраняются в общую с ботом БД; бот подхватывает их в течение ~5 секунд.
"""
import os
import html
import secrets
from itertools import groupby

from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from services import db_service, texts

app = FastAPI(title="Save Video Bot — админка")
security = HTTPBasic()

PANEL_USER = os.getenv("ADMIN_PANEL_USER", "admin")
PANEL_PASSWORD = os.getenv("ADMIN_PANEL_PASSWORD", "")


def auth(credentials: HTTPBasicCredentials = Depends(security)) -> bool:
    ok_user = secrets.compare_digest(credentials.username, PANEL_USER)
    ok_pass = bool(PANEL_PASSWORD) and secrets.compare_digest(credentials.password, PANEL_PASSWORD)
    if not (ok_user and ok_pass):
        raise HTTPException(
            status_code=401,
            detail="Неверный логин или пароль",
            headers={"WWW-Authenticate": "Basic"},
        )
    return True


@app.on_event("startup")
async def _startup():
    await db_service.init_db()


PAGE = """<!doctype html>
<html lang="ru"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Save Video Bot — тексты</title>
<style>
  :root {{ color-scheme: light dark; }}
  * {{ box-sizing: border-box; }}
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; max-width: 860px;
         margin: 0 auto; padding: 24px 16px 96px; line-height: 1.4; }}
  h1 {{ font-size: 22px; }}
  h2 {{ font-size: 15px; text-transform: uppercase; letter-spacing: .04em; opacity: .6;
        margin: 32px 0 8px; border-bottom: 1px solid #8884; padding-bottom: 6px; }}
  .item {{ margin: 18px 0; }}
  .item .label {{ font-weight: 600; }}
  .item .meta {{ font-size: 12px; opacity: .6; margin: 2px 0 6px; }}
  .item .meta code {{ background: #8882; padding: 1px 5px; border-radius: 4px; }}
  textarea {{ width: 100%; min-height: 70px; font: 14px/1.4 ui-monospace, monospace;
             padding: 10px; border-radius: 8px; border: 1px solid #8886;
             background: #8881; color: inherit; resize: vertical; }}
  .row {{ display: flex; gap: 8px; align-items: center; margin-top: 4px; }}
  .reset {{ font-size: 12px; background: none; border: 1px solid #8886; border-radius: 6px;
            padding: 4px 8px; cursor: pointer; color: inherit; }}
  .bar {{ position: fixed; left: 0; right: 0; bottom: 0; padding: 12px 16px; text-align: center;
          background: #1e88e5; }}
  .bar button {{ font-size: 15px; font-weight: 600; padding: 10px 28px; border: none;
                 border-radius: 8px; background: #fff; color: #1e88e5; cursor: pointer; }}
  .saved {{ background: #2e7d32; color: #fff; padding: 10px 14px; border-radius: 8px; margin: 12px 0; }}
</style></head><body>
<h1>📝 Тексты бота</h1>
<p style="opacity:.7;font-size:14px">Правь любой текст и жми «Сохранить». Изменения появятся в боте в течение ~5 секунд.
Доступные переменные указаны под каждым полем — вставляй их в фигурных скобках, например <code>{{first_name}}</code>.</p>
{saved}
<form method="post" action="/save">
{body}
<div class="bar"><button type="submit">💾 Сохранить всё</button></div>
</form>
</body></html>"""


def _render_page(merged: dict, overrides: dict, saved: bool) -> str:
    parts = []
    for group, items in groupby(texts.REGISTRY, key=lambda e: e["group"]):
        parts.append(f"<h2>{html.escape(group)}</h2>")
        for entry in items:
            key = entry["key"]
            value = merged.get(key, entry["default"])
            is_custom = key in overrides
            ph = entry.get("placeholders") or []
            ph_html = ""
            if ph:
                tags = " ".join(f"<code>{{{html.escape(p)}}}</code>" for p in ph)
                ph_html = f" · переменные: {tags}"
            custom_mark = " · <b style='color:#1e88e5'>изменено</b>" if is_custom else ""
            reset_btn = (
                f'<button class="reset" type="submit" formaction="/reset" '
                f'name="resetkey" value="{html.escape(key)}">↺ сбросить к стандартному</button>'
                if is_custom else ""
            )
            parts.append(
                f'<div class="item">'
                f'<div class="label">{html.escape(entry["label"])}</div>'
                f'<div class="meta"><code>{html.escape(key)}</code>{ph_html}{custom_mark}</div>'
                f'<textarea name="text__{html.escape(key)}">{html.escape(value)}</textarea>'
                f'<div class="row">{reset_btn}</div>'
                f'</div>'
            )
    saved_html = '<div class="saved">✅ Сохранено</div>' if saved else ""
    return PAGE.format(body="\n".join(parts), saved=saved_html)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request, _: bool = Depends(auth)):
    overrides = await db_service.get_text_overrides()
    merged = dict(texts.DEFAULTS)
    merged.update({k: v for k, v in overrides.items() if k in texts.DEFAULTS})
    saved = request.query_params.get("saved") == "1"
    return _render_page(merged, overrides, saved)


@app.post("/save")
async def save(request: Request, _: bool = Depends(auth)):
    form = await request.form()
    for field, value in form.items():
        if not field.startswith("text__"):
            continue
        key = field[len("text__"):]
        if key not in texts.DEFAULTS:
            continue
        value = str(value).replace("\r\n", "\n")
        # Совпадает с дефолтом — убираем переопределение, иначе сохраняем
        if value == texts.DEFAULTS[key]:
            await db_service.delete_text(key)
        else:
            await db_service.set_text(key, value)
    return RedirectResponse("/?saved=1", status_code=303)


@app.post("/reset")
async def reset(request: Request, _: bool = Depends(auth)):
    form = await request.form()
    key = form.get("resetkey")
    if key in texts.DEFAULTS:
        await db_service.delete_text(key)
    return RedirectResponse("/?saved=1", status_code=303)
