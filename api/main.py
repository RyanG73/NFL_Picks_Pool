import os
from contextlib import asynccontextmanager
from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from api.routes import public, picks, admin, cron

BASE_DIR = os.path.dirname(__file__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield  # startup / shutdown hooks go here when needed


app = FastAPI(title="NFL Picks Pool", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")

templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

app.include_router(public.router)
app.include_router(picks.router)
app.include_router(admin.router, prefix="/admin")
app.include_router(cron.router, prefix="/api/cron")
