# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller 打包配置 —— 口琴自动演奏器

用法：
    pip install pyinstaller
    pyinstaller 口琴自动演奏器.spec

产物：dist/口琴自动演奏器.exe（单文件，双击即用）

说明：
- 主程序只用标准库 + tkinter，无需 numpy/scipy（那两个只给试听合成脚本用），
  所以这里显式 excludes 掉，能把 exe 从 ~30MB 压到 ~11MB。
- 数据文件（songs.json / config.json）**不打进 exe**：程序用 app_dir() 取
  「exe 所在目录」来读写，这样用户能直接改曲库，升级 exe 也不会覆盖数据。
"""

a = Analysis(
    ['harmonica_autoplay.py'],
    pathex=[],
    binaries=[],
    datas=[
        # 把曲库打进 exe 当「种子」：用户首次运行时释放到 exe 旁边，
        # 这样下载一个 exe 就能直接拥有完整曲库（38 首），而不是只有内置示例。
        ('songs.json', '.'),
    ],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # 试听合成才需要的大块依赖，运行时用不到，排除以减小体积
    excludes=[
        'numpy', 'scipy', 'matplotlib', 'PIL', 'pandas',
        'PyQt5', 'PySide2', 'PySide6', 'IPython', 'pytest',
    ],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='口琴自动演奏器',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,          # GUI 程序，不弹黑框
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='app.ico',
)
