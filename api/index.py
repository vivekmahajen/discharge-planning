import sys
import os

# Add the project root to sys.path so imports work on Vercel
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web_app import app
