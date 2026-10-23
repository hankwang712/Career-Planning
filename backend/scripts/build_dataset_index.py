import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.datasets import build_index


if __name__ == "__main__":
    print(json.dumps(build_index(), ensure_ascii=False))
