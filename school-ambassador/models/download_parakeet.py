import os
import shutil
import tarfile
import urllib.request
from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent
TARGET_DIR = BASE_DIR / "parakeet-tdt-0.6b-v3"
ARCHIVE_PATH = BASE_DIR / "parakeet.tar.bz2"
URL = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8.tar.bz2"

TARGET_DIR.mkdir(parents=True, exist_ok=True)

print("=" * 60)
print("  Downloading NVIDIA Parakeet TDT 0.6B v3 (int8)")
print("  Source: sherpa-onnx (CC-BY-4.0 Attribution: NVIDIA)")
print("=" * 60)
print(f"URL: {URL}")
print("Please wait, downloading ~500MB archive...\n")

def reporthook(blocknum, blocksize, totalsize):
    readsofar = blocknum * blocksize
    if totalsize > 0:
        percent = readsofar * 1e2 / totalsize
        if blocknum % 1000 == 0 or readsofar >= totalsize:
            print(f"  Downloaded {readsofar / (1024*1024):.1f} MB / {totalsize / (1024*1024):.1f} MB ({percent:.1f}%)", end="\r")

try:
    urllib.request.urlretrieve(URL, ARCHIVE_PATH, reporthook)
    print("\n\nDownload complete! Extracting model files...")

    with tarfile.open(ARCHIVE_PATH, "r:bz2") as tar:
        tar.extractall(path=BASE_DIR)

    extracted_dir = BASE_DIR / "sherpa-onnx-nemo-parakeet-tdt-0.6b-v3-int8"
    if extracted_dir.is_dir():
        for item in extracted_dir.iterdir():
            dest = TARGET_DIR / item.name
            if dest.exists():
                dest.unlink()
            shutil.move(str(item), str(TARGET_DIR))
        shutil.rmtree(str(extracted_dir), ignore_errors=True)

    if ARCHIVE_PATH.exists():
        ARCHIVE_PATH.unlink()

    print(f"\nSUCCESS! Parakeet model files installed in: {TARGET_DIR}")
    for f in TARGET_DIR.iterdir():
        print(f"  - {f.name} ({f.stat().st_size / (1024*1024):.1f} MB)")
except Exception as exc:
    print(f"\nError downloading Parakeet model: {exc}")

