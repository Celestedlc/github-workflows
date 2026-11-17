#!/usr/bin/env python3
"""Generador automático de README.md usando el SDK oficial google-genai."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable

from google import genai
from google.genai import errors

MAX_FILE_BYTES = 50 * 1024  # 50 KB
MAX_TOTAL_CONTEXT_CHARS = 400_000
MAX_EXISTING_README_CHARS = 20_000

PREFERRED_MODEL_ALIASES = (
    "gemini-flash-latest",
    "gemini-pro-latest",
    "gemini-2.5-flash",
)

EXCLUDED_VARIANT_RE = re.compile(
    r"(?:^|[-_.])(lite|8b|vision)(?:$|[-_.])", re.IGNORECASE
)
NON_TEXT_VARIANT_RE = re.compile(
    r"(?:^|[-_.])(tts|image|audio|live|robotics|computer-use|embedding|aqa|imagen|veo)(?:$|[-_.])",
    re.IGNORECASE,
)
VERSION_RE = re.compile(r"^gemini-(\d+)(?:\.(\d+))?", re.IGNORECASE)

LOCKFILE_NAMES = frozenset(
    {
        "package-lock.json",
        "npm-shrinkwrap.json",
        "yarn.lock",
        "pnpm-lock.yaml",
        "bun.lock",
        "bun.lockb",
        "poetry.lock",
        "pipfile.lock",
        "uv.lock",
        "pdm.lock",
        "cargo.lock",
        "gemfile.lock",
        "composer.lock",
        "go.sum",
        "flake.lock",
        "pubspec.lock",
        "packages.lock.json",
        "mix.lock",
    }
)

IGNORED_EXTENSIONS = frozenset(
    {
        # Imágenes
        ".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".ico", ".bmp",
        ".tiff", ".tif", ".avif", ".heic", ".psd", ".ai", ".eps",
        # Audio y video
        ".mp3", ".wav", ".ogg", ".flac", ".aac", ".m4a", ".mp4", ".mov",
        ".avi", ".mkv", ".webm", ".wmv",
        # Fuentes
        ".woff", ".woff2", ".ttf", ".otf", ".eot",
        # Documentos y comprimidos
        ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
        ".zip", ".tar", ".gz", ".tgz", ".bz2", ".xz", ".7z", ".rar",
        ".jar", ".war", ".ear", ".whl", ".egg",
        # Binarios, compilados y bases de datos
        ".exe", ".dll", ".so", ".dylib", ".a", ".lib", ".o", ".obj",
        ".bin", ".dat", ".wasm", ".pyc", ".pyo", ".pyd", ".class",
        ".db", ".sqlite", ".sqlite3", ".pkl", ".pickle", ".npy", ".npz",
        ".pt", ".pth", ".onnx", ".safetensors", ".parquet", ".feather",
        ".map", ".lock",
    }
)

PRIORITY_FILENAMES = frozenset(
    {
        "pyproject.toml",
        "setup.py",
        "setup.cfg",
        "requirements.txt",
        "package.json",
        "tsconfig.json",
        "cargo.toml",
        "go.mod",
        "gemfile",
        "composer.json",
        "pom.xml",
        "build.gradle",
        "build.gradle.kts",
        "makefile",
        "dockerfile",
        "docker-compose.yml",
        "docker-compose.yaml",
        "compose.yml",
        "compose.yaml",
    }
)


def _create_client() -> genai.Client:
    """Crea un cliente Gemini leyendo GEMINI_API_KEY del entorno."""
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "La variable de entorno GEMINI_API_KEY no está definida o está vacía."
        )
    return genai.Client(api_key=api_key)


def _model_recency_key(model_id: str) -> tuple[int, int, int, tuple[int, ...], str]:
    """Genera una clave ordenable para priorizar el modelo flash más reciente."""
    lower = model_id.lower()
    match = VERSION_RE.match(lower)
    major = int(match.group(1)) if match else 0
    minor = int(match.group(2)) if (match and match.group(2)) else 0

    is_unstable = any(tok in lower for tok in ("preview", "exp", "experimental"))
    is_stable = 0 if is_unstable else 1

    tail = lower[match.end() :] if match else lower
    extra_nums = tuple(int(n) for n in re.findall(r"\d+", tail))
    return (major, minor, is_stable, extra_nums, lower)


def _select_best_flash_model(candidates: Iterable[str]) -> str | None:
    """Elige el modelo flash más reciente descartando variantes lite, 8b o vision."""
    flash_models = [
        m
        for m in candidates
        if "gemini" in m.lower()
        and "flash" in m.lower()
        and not EXCLUDED_VARIANT_RE.search(m)
    ]
    if not flash_models:
        return None

    clean_text_models = [
        m for m in flash_models if not NON_TEXT_VARIANT_RE.search(m)
    ]
    pool = clean_text_models or flash_models
    return max(pool, key=_model_recency_key)


def get_working_model(client: genai.Client | None = None) -> str:
    """Obtiene un modelo Gemini válido para generateContent a prueba de deprecaciones."""
    if client is None:
        client = _create_client()

    available_ids: list[str] = []
    for model in client.models.list():
        raw_name = getattr(model, "name", None)
        supported_actions = getattr(model, "supported_actions", None) or []
        if not raw_name or "generateContent" not in supported_actions:
            continue
        model_id = raw_name.removeprefix("models/")
        available_ids.append(model_id)

    available_set = set(available_ids)
    for alias in PREFERRED_MODEL_ALIASES:
        if alias in available_set:
            return alias

    best_flash = _select_best_flash_model(available_ids)
    if best_flash:
        return best_flash

    text_candidates = [
        m
        for m in available_ids
        if "gemini" in m.lower()
        and not EXCLUDED_VARIANT_RE.search(m)
        and not NON_TEXT_VARIANT_RE.search(m)
    ]
    if text_candidates:
        return max(text_candidates, key=_model_recency_key)

    raise RuntimeError(
        "No se encontró ningún modelo compatible con generateContent en client.models.list()."
    )


def _list_tracked_files(repo_root: Path) -> list[str]:
    """Lista los archivos trackeados por git usando git ls-files."""
    result = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=repo_root,
        capture_output=True,
        check=True,
    )
    entries = result.stdout.split(b"\x00")
    return [entry.decode("utf-8", errors="replace") for entry in entries if entry]


def _should_ignore_path(rel_path: str) -> bool:
    """Determina si un archivo debe ignorarse por nombre, extensión o tipo lock/min."""
    name = Path(rel_path).name
    lower_name = name.lower()

    if lower_name in LOCKFILE_NAMES:
        return True
    if lower_name.endswith((".min.js", ".min.css", ".bundle.js")):
        return True

    suffix = Path(lower_name).suffix
    return suffix in IGNORED_EXTENSIONS


def _read_text_file(path: Path) -> str | None:
    """Lee un archivo de texto si pesa <= 50KB y no es binario."""
    if not path.is_file() or path.is_symlink():
        return None
    if path.stat().st_size > MAX_FILE_BYTES:
        return None

    raw = path.read_bytes()
    if b"\x00" in raw[:8192]:
        return None

    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _file_priority(rel_path: str) -> tuple[int, int, str]:
    """Prioriza archivos clave de configuración y entrada frente al resto."""
    lower = rel_path.lower()
    name = Path(lower).name
    if name in PRIORITY_FILENAMES or lower.startswith(".github/workflows/"):
        tier = 0
    elif "/" not in lower:
        tier = 1
    else:
        tier = 2
    return (tier, lower.count("/"), lower)


def build_project_context(repo_root: Path) -> tuple[str, int, int]:
    """Construye la estructura y contenido de archivos relevantes del repositorio."""
    tracked_files = _list_tracked_files(repo_root)
    if not tracked_files:
        raise RuntimeError("No hay archivos trackeados por git en el repositorio.")

    tree_text = "\n".join(f"- {p}" for p in sorted(tracked_files))

    existing_readme = ""
    readme_path = repo_root / "README.md"
    if readme_path.is_file():
        content = _read_text_file(readme_path)
        if content:
            existing_readme = content[:MAX_EXISTING_README_CHARS]

    candidate_paths = [
        p
        for p in sorted(tracked_files, key=_file_priority)
        if p != "README.md" and not _should_ignore_path(p)
    ]

    sections: list[str] = []
    used_chars = len(tree_text) + len(existing_readme)
    included_count = 0
    skipped_for_budget = 0

    for rel_path in candidate_paths:
        text = _read_text_file(repo_root / rel_path)
        if text is None:
            continue

        block = f"\n### Archivo: `{rel_path}`\n```\n{text}\n```\n"
        if used_chars + len(block) > MAX_TOTAL_CONTEXT_CHARS:
            skipped_for_budget += 1
            continue

        sections.append(block)
        used_chars += len(block)
        included_count += 1

    parts = [
        f"## Nombre del repositorio\n{repo_root.name}",
        f"## Árbol completo de archivos trackeados ({len(tracked_files)} archivos)\n{tree_text}",
    ]
    if existing_readme:
        parts.append(
            f"## README.md actual (actualizar y corregir según el código real)\n{existing_readme}"
        )
    parts.append("## Contenido de archivos del proyecto\n" + "".join(sections))
    if skipped_for_budget:
        parts.append(
            f"\nNota: se omitieron {skipped_for_budget} archivos adicionales por límite de contexto."
        )

    return "\n\n".join(parts), included_count, len(tracked_files)


def _strip_outer_markdown_fence(text: str) -> str:
    """Elimina un bloque ```markdown ... ``` envolvente si el modelo lo añade."""
    stripped = text.strip()
    lines = stripped.splitlines()
    if len(lines) >= 2 and lines[0].strip().lower() in ("```markdown", "```md", "```"):
        if lines[-1].strip() == "```":
            return "\n".join(lines[1:-1]).strip() + "\n"
    return stripped + "\n"


def generate_readme(client: genai.Client, model_name: str, context: str) -> str:
    """Solicita a Gemini la generación o actualización completa del README.md en inglés."""
    prompt = f"""You are a senior software engineer and technical writer.
Analyze the source code, configuration, and repository structure provided below and generate a clear, accurate, professional, and complete `README.md` **in English**.

Strict rules:
1. Base everything strictly on the actual repository files. Do NOT invent commands, dependencies, endpoints, environment variables, or features that do not exist in the code.
2. If an existing `README.md` is provided, update any outdated information and keep only what remains true according to the current codebase.
3. Return ONLY the raw Markdown content of `README.md` (no introductory text and no outer ```markdown fences wrapping the entire document).
4. Include these sections tailored to the actual project:
   - Title and clear **Description** of the project (what it does and why it exists).
   - **Architecture** (main components, execution/data flow, and technologies used).
   - **Requirements** (language versions, CLI tools, dependencies, or environment variables detected in the code).
   - **Installation** (exact setup steps derived from the project).
   - **Usage** (real commands, scripts, endpoints, or examples based on the actual code).
   - **File Structure** (clear summary based on the real repository tree).

Repository context:
{context}
"""
    response = client.models.generate_content(model=model_name, contents=prompt)
    text = getattr(response, "text", None)
    if not text or not text.strip():
        raise RuntimeError(f"El modelo '{model_name}' devolvió una respuesta vacía.")
    return _strip_outer_markdown_fence(text)


def main() -> int:
    repo_root = Path.cwd()
    try:
        client = _create_client()
        model_name = get_working_model(client)
        print(f"[generate_docs] Modelo seleccionado: {model_name}")

        context, included_count, total_tracked = build_project_context(repo_root)
        print(
            f"[generate_docs] Contexto construido: {included_count} archivos leídos "
            f"de {total_tracked} trackeados."
        )

        try:
            readme_content = generate_readme(client, model_name, context)
        except errors.APIError as exc:
            # Respaldo adicional si un alias falla en tiempo de inferencia
            print(
                f"[generate_docs] Fallo con '{model_name}' ({exc}); buscando modelo alternativo...",
                file=sys.stderr,
            )
            fallback_candidates = [
                m
                for m in (
                    getattr(item, "name", "").removeprefix("models/")
                    for item in client.models.list()
                    if "generateContent" in (getattr(item, "supported_actions", None) or [])
                )
                if m and m != model_name
            ]
            fallback_model = _select_best_flash_model(fallback_candidates)
            if not fallback_model:
                raise
            print(f"[generate_docs] Reintentando con: {fallback_model}")
            readme_content = generate_readme(client, fallback_model, context)

        output_path = repo_root / "README.md"
        output_path.write_text(readme_content, encoding="utf-8")
        print(f"[generate_docs] README.md actualizado correctamente en {output_path}")
        return 0
    except Exception as exc:
        print(f"[generate_docs] Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
