# Build from the repository root:
#   pyinstaller --clean --noconfirm backend/research-agent-sidecar.spec
from PyInstaller.utils.hooks import collect_submodules

hidden = collect_submodules("backend")

a = Analysis(
    ["sidecar.py"],
    pathex=[".."],
    binaries=[],
    datas=[
        ("../frontend/templates", "frontend/templates"),
        ("../frontend/static", "frontend/static"),
    ],
    hiddenimports=hidden,
    hookspath=[],
    runtime_hooks=["backend/pyinstaller_runtime.py"],
    excludes=[
        "accelerate",
        "datasets",
        "huggingface_hub",
        "matplotlib",
        "tensorflow",
        "tkinter",
        "torch",
        "torchaudio",
        "torchvision",
        "transformers",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="research-agent-sidecar",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=False,
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=True,
    name="research-agent-sidecar",
)
