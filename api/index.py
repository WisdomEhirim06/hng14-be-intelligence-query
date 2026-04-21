import sys
import os

# Ensure the project root is on the path so we can import from main.py
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from main import app
