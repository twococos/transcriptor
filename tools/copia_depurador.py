"""Copia la pàgina del depurador al canconer, on és el depurador de l'admin.

    uv run python tools/copia_depurador.py [camí del canconer]   (per defecte, ../guitarreopuntcat)

La pàgina és la mateixa (src/transcriptor/depura/depura.html): servida des de /depurador/ fa servir
l'API de l'admin del canconer (/api/admin/depurador/) i les traces que hi pugen els workers. Torna-la
a copiar cada vegada que la canviïs, i fes-ne commit als dos repositoris.
"""

import shutil
import sys
from pathlib import Path

ORIGEN = Path(__file__).resolve().parents[1] / "src" / "transcriptor" / "depura" / "depura.html"


def main() -> int:
    canconer = Path(sys.argv[1]) if len(sys.argv) > 1 else ORIGEN.parents[4] / "guitarreopuntcat"
    desti = canconer / "public" / "depurador" / "index.html"
    if not (canconer / "package.json").exists():
        print(f"No trobo el canconer a {canconer}")
        return 1
    desti.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ORIGEN, desti)
    print(f"{ORIGEN} -> {desti}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
