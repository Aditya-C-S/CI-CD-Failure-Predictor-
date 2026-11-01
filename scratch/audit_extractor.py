import zipfile
import hashlib
from pathlib import Path
from datetime import datetime

zip_path = Path("models/bilstm2/Retrained_BiLSTM_Final.zip")
extract_dir = Path("scratch/audit_fresh_extract")
extract_dir.mkdir(parents=True, exist_ok=True)

with zipfile.ZipFile(zip_path, "r") as z:
    entries = z.infolist()
    print(f"Total entries in Retrained_BiLSTM_Final.zip: {len(entries)}")
    print(f"{'File Name':<35} {'Size (bytes)':<14} {'Compressed':<12} {'Date/Time':<20} {'CRC32':<12}")
    print("-" * 95)
    for info in entries:
        dt = f"{info.date_time[0]}-{info.date_time[1]:02d}-{info.date_time[2]:02d} {info.date_time[3]:02d}:{info.date_time[4]:02d}:{info.date_time[5]:02d}"
        print(f"{info.filename:<35} {info.file_size:<14} {info.compress_size:<12} {dt:<20} {info.CRC:<12}")
        z.extract(info, extract_dir)

print("\nExtraction complete.")

# Also inspect original zip infolist
orig_zip = Path("models/bilstm/bilstm_Final_Models.zip")
with zipfile.ZipFile(orig_zip, "r") as z:
    orig_entries = z.infolist()
    print(f"\nTotal entries in original bilstm_Final_Models.zip: {len(orig_entries)}")
    print(f"{'File Name':<35} {'Size (bytes)':<14} {'Compressed':<12} {'Date/Time':<20} {'CRC32':<12}")
    print("-" * 95)
    for info in orig_entries:
        dt = f"{info.date_time[0]}-{info.date_time[1]:02d}-{info.date_time[2]:02d} {info.date_time[3]:02d}:{info.date_time[4]:02d}:{info.date_time[5]:02d}"
        print(f"{info.filename:<35} {info.file_size:<14} {info.compress_size:<12} {dt:<20} {info.CRC:<12}")

