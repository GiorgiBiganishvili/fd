"""Collect installed dependency license texts without copying package code."""
import importlib.metadata
import shutil
import sys
from pathlib import Path


def main():
    target = Path(sys.argv[1])
    target.mkdir(parents=True, exist_ok=True)
    inventory = []
    for distribution in importlib.metadata.distributions():
        name = distribution.metadata["Name"]
        inventory.append(f"{name}=={distribution.version}")
        for entry in distribution.files or []:
            if any(term in entry.name.lower() for term in ("license", "notice", "copying")):
                source = Path(distribution.locate_file(entry))
                if source.is_file():
                    directory = target/name
                    directory.mkdir(exist_ok=True)
                    destination = directory/str(entry).replace("/", "_").replace("\\", "_")
                    shutil.copyfile(source, destination)
    (target/"DEPENDENCIES.txt").write_text('\n'.join(sorted(inventory)), "utf-8")


if __name__ == "__main__":
    main()
