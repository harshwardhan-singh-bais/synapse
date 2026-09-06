import inspect

from textual.widgets._footer import FooterKey, FooterLabel
for w in (FooterKey, FooterLabel):
    print("=" * 20, w.__name__, "=" * 20)
    print(inspect.getsource(w))

from pathlib import Path

src = Path("synapse/db/database.py")
print(src.read_text(encoding="utf-8")[:3000])