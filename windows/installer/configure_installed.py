"""Après installation : indique à la DLL où sont le Python embarqué et l'auxiliaire (build/preview.ini, UTF-16)."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP = HERE.parents[1]
(HERE / "build").mkdir(exist_ok=True)
(HERE / "build" / "preview.ini").write_text(
    "[helper]\npython=" + str(APP / "python" / "pythonw.exe")
    + "\nscript=" + str(APP / "explorer_preview" / "shell_preview.py") + "\n",
    encoding="utf-16",
)
