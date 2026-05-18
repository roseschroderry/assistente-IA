import os

import PyInstaller.__main__


base_dir = os.path.abspath(os.path.dirname(__file__))
spec_file = os.path.join(base_dir, "AssistenteElite.spec")

PyInstaller.__main__.run([
    spec_file,
    "--clean",
    "--noconfirm",
])

print("\n--- Build concluido! O executavel esta na pasta 'dist'. ---")
