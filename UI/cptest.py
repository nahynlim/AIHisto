# %%
import os
import sys
import subprocess
from pathlib import Path

valid_ext = {".tif", ".tiff", ".png", ".jpg", ".jpeg"}

files = [
    f for f in os.listdir(input_dir)
    if Path(f).suffix.lower() in valid_ext
]

if len(files) == 0:
    print("ERROR: No valid image files found in input directory.")
    sys.exit(1)

print(f"Found {len(files)} valid image files.")

if not os.path.isdir(output_dir):
    print(f"Output directory does not exist. Creating:\n{output_dir}")
    Path(output_dir).mkdir(parents=True, exist_ok=True)








