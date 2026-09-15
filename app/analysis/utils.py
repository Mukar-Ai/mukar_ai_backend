from __future__ import annotations

import copy
import re
from typing import Any


_PATH_PATTERN = re.compile(
    r"([^[.\]]+)|\[(\d+)\]"
)


def parse_path(path: str) -> list[str | int]:
    parts: list[str | int] = []

    for match in _PATH_PATTERN.finditer(path):
        field, index = match.groups()

        if field is not None:
            parts.append(field)
        else:
            parts.append(int(index))

    if not parts:
        raise ValueError(
            f"Chemin invalide : {path}"
        )

    return parts


def set_nested_value(
    data: dict[str, Any],
    path: str,
    value: Any,
) -> None:

    parts = parse_path(path)

    current: Any = data

    for i, part in enumerate(parts[:-1]):
        next_part = parts[i + 1]

        if isinstance(part, str):

            if not isinstance(current, dict):
                raise TypeError(
                    f"Le chemin {path} n'est pas valide."
                )

            if part not in current or current[part] is None:
                current[part] = (
                    []
                    if isinstance(next_part, int)
                    else {}
                )

            current = current[part]

        else:

            if not isinstance(current, list):
                raise TypeError(
                    f"Le chemin {path} attend une liste."
                )

            while len(current) <= part:
                current.append(
                    []
                    if isinstance(next_part, int)
                    else {}
                )

            current = current[part]

    last = parts[-1]

    if isinstance(last, str):

        if not isinstance(current, dict):
            raise TypeError(
                f"Le chemin {path} attend un objet."
            )

        current[last] = value

    else:

        if not isinstance(current, list):
            raise TypeError(
                f"Le chemin {path} attend une liste."
            )

        while len(current) <= last:
            current.append(None)

        current[last] = value


def update_analysis_input(
    current_json: dict[str, Any],
    llm_result: dict[str, Any],
) -> dict[str, Any]:

    updated = copy.deepcopy(current_json)

    updates = llm_result.get(
        "updates",
        {}
    )

    new_missing = llm_result.get(
        "missing_information",
        []
    )

    new_conflicts = llm_result.get(
        "conflicts",
        []
    )

    updated_fields: set[str] = set()

    # -----------------------------------------
    # 1. Appliquer les updates
    # -----------------------------------------

    for field_path, extracted_value in updates.items():

        if extracted_value.get("value") is None:
            continue

        # Le backend garantit EXTRACTED lorsqu'une vraie donnée
        # est retournée.
        extracted_value["status"] = "EXTRACTED"

        set_nested_value(
            updated,
            field_path,
            extracted_value,
        )

        updated_fields.add(field_path)

    # -----------------------------------------
    # 2. Mettre à jour les informations manquantes
    # -----------------------------------------

    current_missing = updated.get(
        "missing_information",
        []
    )

    remaining_missing = []

    for item in current_missing:

        field = item.get("field")

        if field in updated_fields:
            continue

        remaining_missing.append(item)

    existing_fields = {
        item.get("field")
        for item in remaining_missing
    }

    for item in new_missing:

        field = item.get("field")

        if field not in existing_fields:
            remaining_missing.append(item)
            existing_fields.add(field)

    updated["missing_information"] = remaining_missing

    # -----------------------------------------
    # 3. Ajouter les nouveaux conflits
    # -----------------------------------------

    current_conflicts = updated.get(
        "conflicts",
        []
    )

    current_conflicts.extend(
        new_conflicts
    )

    updated["conflicts"] = current_conflicts

    return updated
