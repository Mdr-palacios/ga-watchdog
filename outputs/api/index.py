"""Vercel serverless entrypoint.

Vercel's Python runtime looks for a module-level `app` callable. This
file just re-exports the FastAPI app from `app.py` so the deployment
surface is a single, well-known import path.
"""

from .app import app  # noqa: F401
