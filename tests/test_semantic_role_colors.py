"""Every semantic role needs a colour in the conditioning renderer.

The ID pass paints each object by its role and the coverage reader decodes the
result by nearest colour, so a role the table does not know is a role the
pipeline cannot see. Adding `canopy` to the scene without adding it here
stopped every view set with a `KeyError` raised inside Blender, hundreds of
lines away from anything that mentioned the role.

The colours must also stay apart: `ValidateConditioningViewSet` matches a pixel
to the nearest entry within 36, so two roles closer than that become one.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from v365_archviz.application.validate_conditioning import (
    CIRCULATION_ROLES,
    CONTEXT_ROLES,
    FOCUS_ROLES,
    SITE_PLAN_ROLES,
)
from v365_archviz.domain.scene import SemanticRole

RENDERER = Path(__file__).resolve().parents[1] / "scripts/blender/render_conditioning.py"
#: The reader's matching radius, in 8-bit sRGB units.
COLOR_TOLERANCE = 36

_ENTRY = re.compile(r'"([a-z_]+)": \(([\d.]+), ([\d.]+), ([\d.]+), 1\.0\)')


def role_colors() -> dict[str, tuple[float, float, float]]:
    source = RENDERER.read_text(encoding="utf-8")
    block = source[source.index("    role_colors = {") : source.index("    semantic_materials = {")]
    return {
        match[1]: (float(match[2]), float(match[3]), float(match[4]))
        for match in _ENTRY.finditer(block)
    }


def test_every_semantic_role_has_a_colour() -> None:
    painted = set(role_colors())
    missing = {role.value for role in SemanticRole} - painted
    assert not missing, (
        f"{sorted(missing)} can be assigned to an element but the conditioning renderer has no "
        "colour for it; the ID pass cannot encode it and the coverage reader cannot see it"
    )


def test_every_role_the_validator_counts_has_a_colour() -> None:
    painted = set(role_colors())
    counted = FOCUS_ROLES | CIRCULATION_ROLES | CONTEXT_ROLES | SITE_PLAN_ROLES
    assert not counted - painted


def test_no_two_roles_share_a_colour_within_the_matching_radius() -> None:
    colors = role_colors()
    too_close = []
    names = sorted(colors)
    for index, first in enumerate(names):
        for second in names[index + 1 :]:
            distance = math.dist(
                [value * 255 for value in colors[first]],
                [value * 255 for value in colors[second]],
            )
            if distance <= COLOR_TOLERANCE:
                too_close.append((first, second, round(distance)))
    assert not too_close, f"roles closer than {COLOR_TOLERANCE} decode as each other: {too_close}"
