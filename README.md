# github-workflows

Repositorio central con un **workflow reutilizable de GitHub Actions** y un script en Python para generar o actualizar automáticamente el archivo `README.md` de otros repositorios mediante la API de Google Gemini (`google-genai`), abriendo un Pull Request con los cambios.

Esta guía explica cómo funciona el proyecto y cómo configurarlo o utilizarlo desde **otros equipos distintos al principal** (ya sea clonándolo en otro ordenador para trabajar/ejecutarlo en local o usándolo desde otros repositorios en GitHub).

---

## Estructura del repositorio

```text
github-workflows/
├── .github/
│   └── workflows/
│       └── reusable-gemini-docs.yml   # Workflow reutilizable (workflow_call)
└── scripts/
    └── generate_docs.py               # Script generador de README.md con Gemini
```

---

## Cómo funciona

1. El workflow [`.github/workflows/reusable-gemini-docs.yml`](.github/workflows/reusable-gemini-docs.yml) se invoca desde otro repositorio mediante `workflow_call`.
2. En el runner (`ubuntu-latest`), hace checkout de:
   - El repositorio destino en `target-repo/`.
   - Este repositorio (`Celestedlc/github-workflows`, rama `main`) en `workflow-repo/`.
3. Configura **Python 3.12** e instala el paquete `google-genai`.
4. Ejecuta [`scripts/generate_docs.py`](scripts/generate_docs.py) dentro de `target-repo/`, el cual:
   - Lee la variable de entorno `GEMINI_API_KEY`.
   - Selecciona automáticamente un modelo compatible con `generateContent` (priorizando `gemini-flash-latest`, `gemini-pro-latest`, `gemini-2.5-flash` o el modelo `flash` de texto más reciente disponible; con respaldo automático si falla en inferencia).
   - Recopila el árbol de archivos trackeados por Git (`git ls-files -z`), prioriza archivos clave de configuración/workflows y el `README.md` existente (hasta `20_000` caracteres), ignorando binarios, lockfiles, minificados y archivos mayores de `50 KB`, con un límite total de contexto de `400_000` caracteres.
   - Genera el nuevo `README.md` (en inglés, según el prompt definido en `generate_readme()`) y lo guarda en la raíz del repositorio destino.
5. Si `README.md` cambia, `peter-evans/create-pull-request@v7` crea o actualiza un Pull Request desde la rama `docs/auto-update` (`delete-branch: true`).

---

## Opción 1: Usarlo en otros repositorios de GitHub (desde cualquier equipo)

Al ser un workflow en GitHub Actions, no depende de tu ordenador principal. Solo necesitas configurar el repositorio destino y tener acceso a tus credenciales desde el navegador o `git`.

### 1. Configurar secretos en el repositorio destino

En GitHub, ve al repositorio donde quieres automatizar el `README.md`: **Settings → Secrets and variables → Actions → New repository secret**.

| Secreto | Obligatorio | Descripción |
| --- | --- | --- |
| `GEMINI_API_KEY` | Sí | Tu API Key de Google Gemini. No se guarda en el repositorio; debes copiarla desde tu gestor de contraseñas o Google AI Studio cuando configures un repo nuevo. |
| `WORKFLOW_REPO_TOKEN` | Solo si este repo es privado | Personal Access Token (PAT) con permiso de lectura (`Contents: Read`) sobre `Celestedlc/github-workflows` para poder hacer checkout de `scripts/generate_docs.py`. Si no se define, el workflow usa `github.token`. |

> **Nota sobre visibilidad:** Si `Celestedlc/github-workflows` es un repositorio privado, además del `WORKFLOW_REPO_TOKEN`, en **Settings → Actions → General → Access** de `Celestedlc/github-workflows` debe permitirse el acceso desde los otros repositorios (o ser accesible dentro de la misma cuenta/organización según la configuración de GitHub).

### 2. Habilitar permisos para crear Pull Requests

En el repositorio destino, ve a **Settings → Actions → General → Workflow permissions** y asegúrate de tener habilitado:
- **Read and write permissions**
- **Allow GitHub Actions to create and approve pull requests**

### 3. Crear el workflow llamador en el repositorio destino

Crea un archivo como `.github/workflows/update-readme.yml` en el repositorio destino:

```yaml
name: Update README with Gemini

on:
  workflow_dispatch:
  push:
    branches:
      - main

permissions:
  contents: write
  pull-requests: write

jobs:
  docs:
    uses: Celestedlc/github-workflows/.github/workflows/reusable-gemini-docs.yml@main
    secrets:
      GEMINI_API_KEY: ${{ secrets.GEMINI_API_KEY }}
      WORKFLOW_REPO_TOKEN: ${{ secrets.WORKFLOW_REPO_TOKEN }} # Omitir si no se usa
```

> Si el workflow llamador no tiene activado `workflow_dispatch`, puedes ajustarlo a los eventos que necesites (`push`, `schedule`, manual, etc.).

---

## Opción 2: Usarlo o mantenerlo en local desde otro ordenador

Si cambias de equipo (portátil, sobremesa, máquina virtual, etc.) y quieres editar este repositorio o ejecutar `scripts/generate_docs.py` localmente sobre un proyecto, sigue estos pasos.

### Requisitos previos en el nuevo equipo

- **Git** instalado y autenticado contra GitHub (clave SSH o HTTPS con token/credenciales, necesario para clonar `Celestedlc/github-workflows` y para que `git ls-files` funcione en los repositorios destino).
- **Python 3.12** (versión usada en el workflow; el código requiere Python ≥ 3.10 por la sintaxis de tipos y `str.removeprefix`).
- **API Key de Google Gemini** (`GEMINI_API_KEY`) disponible en ese equipo.

### 1. Clonar el repositorio e instalar dependencias

En Linux / macOS:

```bash
git clone https://github.com/Celestedlc/github-workflows.git
cd github-workflows
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip google-genai
```

En Windows (PowerShell):

```powershell
git clone https://github.com/Celestedlc/github-workflows.git
cd github-workflows
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip google-genai
```

*(Si prefieres clonar por SSH, usa `git@github.com:Celestedlc/github-workflows.git` una vez tengas tu clave SSH añadida en GitHub).*

### 2. Configurar `GEMINI_API_KEY` en el nuevo equipo

La clave no forma parte del repositorio. Defínela en la sesión actual (o en la configuración de tu terminal/sistema):

- **Linux / macOS (bash/zsh):**
  ```bash
  export GEMINI_API_KEY="tu_api_key_aqui"
  ```
- **Windows (PowerShell):**
  ```powershell
  $env:GEMINI_API_KEY="tu_api_key_aqui"
  ```

### 3. Ejecutar el generador en local contra un proyecto

El script toma siempre como repositorio objetivo el **directorio de trabajo actual** (`Path.cwd()`). Sitúate en la raíz del proyecto que quieras documentar y ejecuta `generate_docs.py`:

```bash
cd /ruta/a/tu-proyecto
python /ruta/a/github-workflows/scripts/generate_docs.py
```

En Windows (PowerShell), con el entorno virtual activado o usando su `python.exe`:

```powershell
cd C:\ruta\a\tu-proyecto
C:\ruta\a\github-workflows\.venv\Scripts\python.exe C:\ruta\a\github-workflows\scripts\generate_docs.py
```

**Importante al ejecutar en local:**
- El directorio destino debe ser un repositorio Git con al menos los archivos añadidos al índice/trackeados (`git add`), ya que el script usa `git ls-files -z`. Si no hay archivos trackeados, fallará.
- A diferencia del workflow de GitHub Actions, la ejecución local **sobrescribe directamente `README.md` en el directorio actual** sin crear rama ni Pull Request. Revisa el resultado con `git diff README.md` antes de hacer commit.
- El `README.md` generado por `generate_docs.py` se redacta siempre **en inglés**. Tenlo en cuenta si ejecutas el script sobre un repositorio cuya documentación prefieres mantener en español (incluido este mismo repo).

---

## Solución de problemas frecuentes en equipos nuevos

- **`La variable de entorno GEMINI_API_KEY no está definida o está vacía.`**
  No has exportado `GEMINI_API_KEY` en la terminal actual o falta el secreto en el repositorio de GitHub.
- **`No hay archivos trackeados por git en el repositorio.`**
  Estás ejecutando el script fuera de un repo Git o todavía no has hecho `git add` de los archivos del proyecto.
- **Error al hacer checkout de `Celestedlc/github-workflows` en GitHub Actions**
  Si el repo es privado, verifica que `WORKFLOW_REPO_TOKEN` exista en el repo destino, no haya caducado y tenga acceso de lectura sobre `Celestedlc/github-workflows`.
- **Error al crear el Pull Request en GitHub Actions**
  Revisa que el workflow llamador declare `permissions: contents: write` y `pull-requests: write`, y que en los ajustes del repositorio destino esté permitido que GitHub Actions cree Pull Requests.
