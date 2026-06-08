"""
Torre de Controle Logística Inteligente
Entrypoint FastAPI — integração Winthor + Fusion + IA
"""
import logging
import logging.handlers
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.requests import Request
from fastapi.responses import HTMLResponse

from app.config import settings
from app.database.oracle import check_connection
from app.routers import consulta, alertas, whatsapp, discovery

# ── Logging ───────────────────────────────────────────────────────────────────
log_dir = Path("app/logs")
log_dir.mkdir(exist_ok=True)

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.handlers.RotatingFileHandler(
            log_dir / "torre-controle.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        ),
    ],
)
logger = logging.getLogger(__name__)

# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title="Torre de Controle Logística",
    description=(
        "Central Inteligente de Entregas e Devoluções.\n"
        "Integra Winthor + Fusion para status unificado de pedidos."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

# Arquivos estáticos e templates
BASE = Path(__file__).parent
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
templates = Jinja2Templates(directory=BASE / "templates")

# Routers
app.include_router(consulta.router)
app.include_router(alertas.router)
app.include_router(whatsapp.router)
app.include_router(discovery.router)


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health", tags=["Health"])
def health():
    return {"status": "ok", "app": settings.app_name}


@app.get("/health/oracle", tags=["Health"])
def health_oracle():
    return check_connection()


# ── Portal web ────────────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse, include_in_schema=False)
def portal(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "app_name": settings.app_name,
        "fusion_enabled": settings.fusion_enabled,
        "ai_enabled": settings.ai_enabled,
        "whatsapp_enabled": settings.whatsapp_enabled,
    })


# ── Startup ───────────────────────────────────────────────────────────────────

@app.on_event("startup")
async def startup():
    logger.info("=" * 60)
    logger.info("Torre de Controle Logística iniciando...")
    logger.info("  Oracle:   %s:%s", settings.oracle_host, settings.oracle_port)
    logger.info("  Fusion:   %s", "ATIVO" if settings.fusion_enabled else "desabilitado (mock)")
    logger.info("  IA:       %s", "ATIVA" if settings.ai_enabled else "desabilitada")
    logger.info("  WhatsApp: %s", "ATIVO" if settings.whatsapp_enabled else "desabilitado")
    logger.info("=" * 60)
