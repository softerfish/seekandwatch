"""
pytest configuration file - automatically loaded before running tests

this file sets up the python path so tests can import app modules
when running in Docker (where tests are in /config/tests/ but app is in /app/)
"""

import sys
import os

# add parent directory to path so tests can import app modules
# this works for both local dev (seekandwatch/tests/) and Docker (/config/tests/)
parent_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# also add /app to path for Docker environment
if os.path.exists('/app') and '/app' not in sys.path:
    sys.path.insert(0, '/app')
