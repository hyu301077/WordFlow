# -*- mode: python ; coding: utf-8 -*-
"""WordFlow 的 PyInstaller 配置。词典存在时一并打包，因此输出目录会比较大。"""

from pathlib import Path

from PyInstaller.utils.hooks import collect_all

root = Path(SPECPATH).resolve().parent
datas = [
    (str(root / "data" / "stopwords.txt"), "data"),
    (str(root / "data" / "confusion_pairs.txt"), "data"),
]
binaries = []
hidden = [
    "win32com",
    "win32com.client",
    "pythoncom",
    "fsrs",
    "pypdfium2",
    "pypdfium2_raw",
    "PIL",
    "PIL.Image",
    "winrt.windows.media.ocr",
    "winrt.windows.graphics.imaging",
    "winrt.windows.storage.streams",
    "winrt.windows.globalization",
    "winrt.windows.foundation",
]
dictionary = root / "data" / "ecdict.db"
if dictionary.is_file():
    datas.append((str(dictionary), "data"))
for package in (
    "pypdfium2",
    "pypdfium2_raw",
    "winrt",
    "PIL",
    "fsrs",
    "faster_whisper",
    "ctranslate2",
    "imageio_ffmpeg",
    "av",
    "onnxruntime",
    "tokenizers",
    "huggingface_hub",
):
    package_datas, package_binaries, package_hidden = collect_all(package)
    datas += package_datas
    binaries += package_binaries
    hidden += package_hidden

a = Analysis(
    [str(root / "wordflow" / "__main__.py")],
    pathex=[str(root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="WordFlow",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="WordFlow",
)
