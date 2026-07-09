"""Cloud-deployment readiness: host/port resolution, render.yaml, and the Dockerfile.

These guard the free Render deployment (https://protocol-to-data.onrender.com) and any other
$PORT-driven host (Railway / Fly / Cloud Run). Pure/offline — no network, no API key.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import app  # noqa: E402  — repo-root Gradio module


# ---- host binding -----------------------------------------------------------------------

def test_host_defaults_to_localhost():
    assert app._resolve_host(env={}) == "127.0.0.1"


def test_host_binds_all_interfaces_on_hf_spaces():
    assert app._resolve_host(env={"SPACE_ID": "user/space"}) == "0.0.0.0"


def test_host_explicit_override_wins():
    assert app._resolve_host(env={"GRADIO_SERVER_NAME": "0.0.0.0"}) == "0.0.0.0"


# ---- port resolution (precedence: PORT > GRADIO_SERVER_PORT > 7860) ----------------------

def test_port_defaults_to_7860():
    assert app._resolve_port(env={}) == 7860


def test_platform_port_wins_over_everything():
    # Render/Railway/Fly/Cloud Run inject $PORT; it must win even if the image baked 7860.
    assert app._resolve_port(env={"PORT": "10000", "GRADIO_SERVER_PORT": "7860"}) == 10000


def test_gradio_server_port_used_when_no_platform_port():
    assert app._resolve_port(env={"GRADIO_SERVER_PORT": "8080"}) == 8080


# ---- build-SHA marker (verifiable deploys) ----------------------------------------------

def test_build_marker_from_render_commit():
    # Render auto-sets RENDER_GIT_COMMIT; the marker is the 7-char short SHA.
    assert app._build_marker(env={"RENDER_GIT_COMMIT": "09a1351abcdef"}) == "09a1351"


def test_build_marker_falls_back_to_local():
    assert app._build_marker(env={}) == "local"


def test_build_marker_honors_generic_source_commit():
    assert app._build_marker(env={"SOURCE_COMMIT": "abcdef1234"}) == "abcdef1"


# ---- render.yaml blueprint --------------------------------------------------------------

def test_render_blueprint_is_configured():
    text = (ROOT / "render.yaml").read_text()
    assert "runtime: docker" in text          # builds from the Dockerfile, not a buildpack
    assert "dockerfilePath: ./Dockerfile" in text
    assert "plan: free" in text               # free tier
    assert "ANTHROPIC_API_KEY" in text
    assert "sync: false" in text              # secret set in dashboard, never committed


# ---- Dockerfile cloud-readiness ---------------------------------------------------------

def test_dockerfile_is_cloud_ready():
    text = (ROOT / "Dockerfile").read_text()
    assert "python:3.12-slim" in text                 # slim base
    assert "GRADIO_SERVER_NAME=0.0.0.0" in text        # binds all interfaces in a container
    assert "EXPOSE 7860" in text
    assert "USER appuser" in text                      # drops root at runtime
    # requirements copied and installed before the app source (layer caching)
    assert text.index("requirements.txt") < text.index("COPY . .")
