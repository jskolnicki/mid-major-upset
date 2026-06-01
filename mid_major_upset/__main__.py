"""Allow running as: python -m mid_major_upset"""
import sys
from pathlib import Path

# Add project root to path so utils/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from utils.ssh_tunnel import setup_ssh_tunnel_if_configured
setup_ssh_tunnel_if_configured()

from .main import main
main()
