"""populate_spells.py — add every spell name found in a directory to a JSON file's known_spells list.

Usage:
    python tools/populate_spells.py <spells_dir> <creature_json>

Arguments:
    spells_dir      Directory to scan (recursively) for spell JSON files.
    creature_json   Path to the creature JSON file whose "known_spells" list will be updated.

Spell names already present in the list are not duplicated.
"""

import argparse
import json
from pathlib import Path


def collect_spell_names(spells_dir: str) -> list[str]:
    names = []
    for path in sorted(Path(spells_dir).rglob("*.json")):
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        name = data.get("name")
        if name:
            names.append(name)
    return names


def update_known_spells(creature_json: str, spell_names: list[str]) -> None:
    path = Path(creature_json)
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    existing = set(data.get("known_spells", []))
    added = [n for n in spell_names if n not in existing]
    data["known_spells"] = sorted(existing | set(spell_names))

    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")

    print(f"Added {len(added)} spell(s) to {path.name}: {added if added else '(none new)'}")
    print(f"Total known spells: {len(data['known_spells'])}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Populate known_spells in a creature JSON from a spells directory.")
    parser.add_argument("spells_dir", help="Directory containing spell JSON files")
    parser.add_argument("creature_json", help="Creature JSON file to update")
    args = parser.parse_args()

    spell_names = collect_spell_names(args.spells_dir)
    if not spell_names:
        print("No spell files found.")
        return
    update_known_spells(args.creature_json, spell_names)


if __name__ == "__main__":
    main()
