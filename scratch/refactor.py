import os
import glob

# 1. Update pyproject.toml
with open("pyproject.toml", "r", encoding="utf-8") as f:
    content = f.read()
if "loguru" not in content:
    content = content.replace('"playwright>=1.58.0",', '"playwright>=1.58.0",\n    "loguru>=0.7.2",')
    with open("pyproject.toml", "w", encoding="utf-8") as f:
        f.write(content)

# 2. Replace prints with loguru
def process_file(filepath):
    with open(filepath, "r", encoding="utf-8") as f:
        lines = f.readlines()
    
    new_lines = []
    needs_logger = False
    for line in lines:
        if "print(" in line:
            # Simple replacements for log levels
            if "❌" in line or "error" in line.lower() or "failed" in line.lower():
                line = line.replace("print(", "logger.error(")
            elif "⚠️" in line or "warning" in line.lower():
                line = line.replace("print(", "logger.warning(")
            elif "✅" in line or "🎉" in line or "success" in line.lower():
                line = line.replace("print(", "logger.success(")
            else:
                line = line.replace("print(", "logger.info(")
            needs_logger = True
        new_lines.append(line)
        
    if needs_logger:
        # Check if import is already there
        if "from loguru import logger" not in "".join(new_lines):
            # insert after docstring or future imports
            insert_idx = 0
            for i, l in enumerate(new_lines):
                if l.startswith("import ") or l.startswith("from "):
                    insert_idx = i
                    break
            new_lines.insert(insert_idx, "from loguru import logger\n")
                
    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(new_lines)

for root, _, files in os.walk("src"):
    for file in files:
        if file.endswith(".py"):
            process_file(os.path.join(root, file))

print("Refactoring prints to loguru complete.")
