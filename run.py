"""Run without installing: python run.py run --pack pack --out sample_run"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "src"))
from nadi9.cli import main  # noqa: E402

sys.exit(main())
