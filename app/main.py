import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator
from fastapi import FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.schemas import ErrorResponse, LinkAnalysisRequest, LinkAnalysisResponse
from app.services.analysis_service import analyze_url_pipeline
from app.services.llm_service import LLMConfigurationException, LLMServiceException
from app.services.website_extractor import (
    EmptyContentException,
    WebsiteExtractionException,
    WebsiteTimeoutException,
    WebsiteUnreachableException,
)
from app.utils.validators import InvalidURLException, SSRFSecurityException

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("link_analysis_api")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and shutdown lifecycle."""
    settings = get_settings()
    logger.info("Initializing AI-Powered Website Link Analysis API...")
    logger.info(f"Target Port: {settings.PORT} | Default Model: {settings.GEMINI_MODEL}")
    yield
    logger.info("Shutting down API service.")


app = FastAPI(
    title="AI-Powered Website Link Analysis API",
    description=(
        "Production-grade FastAPI application that extracts website content and uses "
        "Google Gemini (gemini-3.5-flash-lite) to generate structured business, competitor, "
        "SEO, search query, and target audience intelligence."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    lifespan=lifespan,
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Exception Handlers
@app.exception_handler(InvalidURLException)
async def invalid_url_handler(request: Request, exc: InvalidURLException) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"success": False, "error": "Invalid URL", "detail": str(exc)},
    )


@app.exception_handler(SSRFSecurityException)
async def ssrf_exception_handler(request: Request, exc: SSRFSecurityException) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "success": False,
            "error": "URL Blocked (SSRF Protection)",
            "detail": str(exc),
        },
    )


@app.exception_handler(WebsiteTimeoutException)
async def website_timeout_handler(request: Request, exc: WebsiteTimeoutException) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_504_GATEWAY_TIMEOUT,
        content={"success": False, "error": "Website Request Timeout", "detail": exc.message},
    )


@app.exception_handler(WebsiteUnreachableException)
async def website_unreachable_handler(request: Request, exc: WebsiteUnreachableException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"success": False, "error": "Website Inaccessible", "detail": exc.message},
    )


@app.exception_handler(EmptyContentException)
async def empty_content_handler(request: Request, exc: EmptyContentException) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={"success": False, "error": "Empty Website Content", "detail": exc.message},
    )


@app.exception_handler(LLMConfigurationException)
async def llm_config_handler(request: Request, exc: LLMConfigurationException) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"success": False, "error": "LLM Configuration Error", "detail": exc.message},
    )


@app.exception_handler(LLMServiceException)
async def llm_service_handler(request: Request, exc: LLMServiceException) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_502_BAD_GATEWAY,
        content={"success": False, "error": "LLM Processing Error", "detail": exc.message},
    )


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    errors = exc.errors()
    first_msg = errors[0]["msg"] if errors else "Validation failed"
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={
            "success": False,
            "error": "Request Validation Failed",
            "detail": first_msg,
        },
    )


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception(f"Unhandled exception during request processing: {exc}")
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "error": "Internal Server Error",
            "detail": "An unexpected server error occurred. Please try again later.",
        },
    )


# API Endpoints
@app.get("/health", summary="Health Check")
async def health_check():
    """Service health and readiness check."""
    settings = get_settings()
    return {
        "status": "healthy",
        "service": "AI-Powered Website Link Analysis API",
        "model": settings.GEMINI_MODEL,
        "port": settings.PORT,
    }


@app.post(
    "/link-analysis",
    response_model=LinkAnalysisResponse,
    responses={
        200: {"model": LinkAnalysisResponse, "description": "Structured website link analysis."},
        400: {"model": ErrorResponse, "description": "Invalid URL or SSRF security violation."},
        422: {"model": ErrorResponse, "description": "Website inaccessible or content unextractable."},
        502: {"model": ErrorResponse, "description": "LLM service or API failure."},
        504: {"model": ErrorResponse, "description": "Target website connection timed out."},
    },
    summary="Analyze Website URL",
    description=(
        "Analyzes a submitted website URL, extracts textual and metadata elements, "
        "and leverages Google Gemini to produce 5 core intelligence sections: "
        "Competitor Analysis, Target Search Queries, SEO Improvements, Top Services, "
        "and Target Audience profiles."
    ),
)
async def link_analysis(payload: LinkAnalysisRequest):
    """Execute end-to-end link analysis pipeline for the requested URL."""
    result = await analyze_url_pipeline(payload.url)
    return result


if __name__ == "__main__":
    import uvicorn
    cfg = get_settings()
    uvicorn.run("app.main:app", host=cfg.HOST, port=cfg.PORT, reload=True)
