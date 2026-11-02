# ADR 0008 — Windows one-click installer (`install.exe` / `uninstall.exe`) instead of a bundled runtime

* **Status:** Accepted
* **Date:** 2026-11-02
* **Deciders:** platform team

## Context

The target operator for the console is a content producer on a Windows laptop, not a Python
developer. `python -m venv`, `pip install -e .` and `uvicorn --app-dir backend` are three
commands and two failure modes (no Python at all, corporate proxy in front of PyPI) away from a
dead end. Docker is not an option either: WSL2/Hyper-V is frequently disabled on managed
corporate machines and IT will not enable it for one app.

At the same time the application is a real Python service (FastAPI + SQLAlchemy + Pillow +
python-docx + FFmpeg) that must keep working as a normal checkout for developers and CI. The
deployment change must not fork the codebase.

## Decision

* **Ship two self-contained executables**, built by `scripts/build_installers.py` with
  PyInstaller (`--onefile --console`):
  * `install.exe` — bootstraps and installs the application;
  * `uninstall.exe` — removes the environment it created.
* **The installers are pure standard library.** They are frozen with a python.org CPython and
  only use `os`/`socket`/`subprocess`/`tomllib`/`urllib`/`winreg`. That is what lets them run on
  a machine with no Python — the exact case they exist for. (A conda interpreter cannot be used
  to freeze them: its `_ssl` builds link OpenSSL DLLs that PyInstaller does not bundle, so the
  frozen exe cannot do HTTPS, and `--selftest` now fails the build if that regresses.)
* **Per-user install, no admin rights**: `%LOCALAPPDATA%\AIFilmStudio` with `app\`, `venv\`,
  `data\`, `start-studio.cmd`, `install.json`. Uninstall is an `HKCU\...\Uninstall\AIFilmStudio`
  entry, so the app also appears in *Settings → Apps*.
* **The payload is embedded in `install.exe`**, so a single file (plus `uninstall.exe`) is the
  whole release. The application is staged into `build/payload` at build time, with `installer/`,
  `.git/`, `.venv/`, `data/`, `build/`, `dist/`, `.env*` and caches excluded. `.env` is never
  shipped: secrets stay on the operator's machine.
* **Dependencies are resolved at install time, not build time**: `pyproject.toml` is parsed with
  `tomllib` and installed into a fresh `venv` with `pip`. `--extras s3,pdf` opts into optional
  packages. This keeps one dependency list for the installer, the checkout and the Docker image.
* **Python is a bootstrap step, not a premise**: probe `py -3.12`/`python`/known install paths
  for CPython ≥ 3.11; if nothing is found, download the official
  `python-3.12.10-amd64.exe` and install it `/quiet InstallAllUsers=0 TargetDir=<root>\python`.
  The private copy never touches `PATH`.
* **`uninstall.exe` keeps user data by default.** It stops processes whose executable lives under
  the install root, deletes shortcuts, the registry entry, `app\`, `venv\` and the private Python,
  and leaves `data\` (SQLite + generated media). `--purge` deletes that too. Deleting a customer's
  films because they clicked "uninstall" is not an acceptable default.
* **`backend/app/desktop.py` is the launcher**: `uvicorn app.main:app` on 127.0.0.1, a free-port
  probe, a browser that opens once `/health` answers, and a banner with env/data/ffmpeg. The
  shortcut points at `start-studio.cmd`, which pins `APP_ENV`, `APP_DATA_DIR`, `STORAGE_ROOT` and
  `PYTHONPATH` so the installed copy is self-contained.
* **Both exes and the build script expose `--selftest` / `--dry-run`.** `--selftest` is wired into
  the build so a broken frozen exe fails the build, not the customer.

## Consequences

**Positive**

* One file to distribute; double-click deploys on a clean Windows box, no admin rights, no WSL,
  no Docker, no Python knowledge.
* `data\` survives upgrades and accidental uninstalls; upgrades are just "run the new
  `install.exe`" — it stops the running studio first, reuses `venv\`, re-copies `app\`.
* The frozen installers are tiny (~8 MB) because they carry no third-party runtime. Dependencies
  are the same wheels every other deployment uses.
* Shortcuts, console window and the *Settings → Apps* entry make the product feel like a normal
  Windows app, and give support a canonical "how to remove it" answer.

**Negative**

* Installing requires network access to python.org (only when no Python exists) and to PyPI.
  Air-gapped sites need a wheel mirror (`PIP_INDEX_URL`) or the source/Docker route.
* The exes are unsigned: SmartScreen will warn on first run. Code signing is the fix, and it is
  a release-process cost, not a code change.
* Install-time dependency resolution means two installs of the same `install.exe` can get
  different patch versions. Reproducibility lives in the repo (`pip freeze` in `venv\`), not in
  the exe.
* PyInstaller onefile unpacks to `%TEMP%\_MEIxxxx` on every run; the payload copy is a few MB, so
  it is measurable but irrelevant for an installer.
* The windowed-launcher model means the app stops when the console window is closed. Acceptable
  for a single-user local tool, wrong for a server.

## Alternatives considered

1. **`pipx` / a `.pyz` with an embedded interpreter** — still needs an existing Python, which is
   the problem being solved.
2. **The Windows *embeddable* Python zip as the runtime** — smallest download, but it ships
   without `pip` and with a restrictive `._pth`; users end up editing config files to install
   anything. A silent full installer plus `venv` is dirtier but boring and robust.
3. **A bundled runtime inside `install.exe` (PyInstaller for the whole app)** — one download and
   no `pip`, but ~200 MB, and every dependency change requires a new build; it also breaks the
   "edit a YAML, restart" workflow because config would be baked into the archive.
4. **MSI via WiX/Inno Setup** — proper Windows packaging (repair, per-machine installs, signing)
   at the cost of a second toolchain and a build machine we would have to maintain. Revisit if we
   need machine-wide installs or Group Policy deployment.
5. **Docker Desktop for Windows** — excluded by the corporate-machine reality described above.
6. **A `.bat` that runs `pip install`** — the "installer" most projects ship; fails exactly when
   Python is missing or unwritable, and leaves nothing to uninstall.

## Revisit when

* Customers need machine-wide (all users) installation or GPO/Intune deployment: move to MSI.
* The exe grows past ~50 MB or dependency drift becomes support noise: ship a pinned
  `requirements.lock` inside the payload and install from it.
* A Linux/macOS desktop story is requested: `installer/common.py` is POSIX-aware, but shortcuts
  and the registry are Windows-only and would need a separate front end.
* Windows' built-in `python` routing or the Microsoft Store Python becomes a reliable ≥3.11
  baseline: the download-and-install-a-private-copy branch could be dropped.
