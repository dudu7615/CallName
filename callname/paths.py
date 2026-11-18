"""程序路径常量：便携模式，所有可变数据都在程序目录旁。"""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WEB_DIR = Path(__file__).resolve().parent / "web"
DB_PATH = ROOT / "callname.db"
ICON = ROOT / "icon.png"
