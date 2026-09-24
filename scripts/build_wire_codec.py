"""Build the portable host codec used by pytest cross-language tests.

Uses g++/clang++ if available, otherwise the optional ziglang Python package.
Run from any directory; generated files stay in output/ (gitignored).
"""
import importlib.util
import os
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
out = root / "output/wire-codec"
out.mkdir(parents=True, exist_ok=True)
compiler = shutil.which("g++") or shutil.which("clang++")
if compiler:
    command = [compiler]
elif importlib.util.find_spec("ziglang"):
    command = [sys.executable, "-m", "ziglang", "c++"]
    if os.name == "nt":
        command += ["-target", "x86_64-windows-gnu"]
else:
    raise SystemExit("Install g++/clang++ or the optional ziglang==0.14.1 package first.")
env = dict(os.environ, ZIG_GLOBAL_CACHE_DIR=str(root / "output/zig-cache"))
target = out / ("codec_cli.exe" if os.name == "nt" else "codec_cli")
subprocess.run(command + ["-std=c++11", "-Wall", "-Wextra", "-Werror",
                         str(root / "firmware/codec/codec_cli.cpp"), "-o", str(target)],
               check=True, cwd=root, env=env)
print(target)
