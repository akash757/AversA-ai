
## This file is for deploy on vercel

import sys
from pathlib import Path

# Add the project root to sys.path so modules like main.py can be imported
sys.path.append(str(Path(__file__).resolve().parent.parent))

from main import app
