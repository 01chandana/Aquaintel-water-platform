"""CORS whitelist (Ch. 17.5.2: no wildcard origins outside development)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import Settings


def add_cors(app: FastAPI, settings: Settings) -> None:
    origins = settings.cors_origins
    if settings.environment == "production" and "*" in origins:
        raise RuntimeError("Wildcard CORS origin is not allowed in production (Ch. 17.5.2)")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-API-Key", "X-Request-ID"],
        expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining", "X-RateLimit-Reset"],
    )
