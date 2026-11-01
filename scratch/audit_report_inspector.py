from pathlib import Path

report_path = Path("scratch/audit_fresh_extract/capstone_final_defense_report.md")
text = report_path.read_text(encoding="utf-8")

lines = text.split("\n")
print("Total lines in capstone_final_defense_report.md:", len(lines))

# Search for Section 6 (Held-out locked test vault)
start_sec6 = False
sec6_lines = []
for l in lines:
    if "## 6. Held-out locked test vault" in l:
        start_sec6 = True
    elif start_sec6 and l.startswith("## 7."):
        break
    if start_sec6:
        sec6_lines.append(l)

print("\n--- Section 6 Content ---")
print("\n".join(sec6_lines[:45]))

