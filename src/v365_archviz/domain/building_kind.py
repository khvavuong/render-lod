"""What a Site Forma building is, beyond its role, and the parts the editor drew on it.

The three roles (main shed, office, utility block) decide how a building is planned and rendered.
The editor knows more: which kind of building each box is (a warehouse, a guard house, a pump
house...), which side is its front, and the parts it drew in detail. These ride along so prompts
can name each building; a building sent without them is planned and described as before.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from v365_archviz.domain.common import DomainModel

BuildingKind = Literal[
    "warehouse",
    "office_block",
    "guard_house",
    "substation",
    "vehicle_shed",
    "refuse_house",
    "pump_house",
    "generic",
]
Compass = Literal["north", "east", "south", "west"]
RoofForm = Literal["gable", "mono_pitch", "flat"]
#: What a building's walls or roof are made of, as the editor's Materials fields set them.
BuildingMaterial = Literal["concrete", "precast", "steel", "brick", "wood", "glass"]


class BuildingFeatures(DomainModel):
    """The parts the editor drew on a building; any of them may be left out."""

    roof: RoofForm | None = None
    roof_slope_deg: float | None = Field(default=None, ge=0, le=45)
    #: Height of the walls, below the roof; the box height is to the highest point.
    eave_height_m: float | None = Field(default=None, gt=0, le=500)
    #: Grade-level roller shutter doors on the front facade.
    front_doors: int | None = Field(default=None, ge=0, le=50)
    #: Roller shutter doors in each end wall.
    end_wall_doors: int | None = Field(default=None, ge=0, le=10)
    canopy_depth_m: float | None = Field(default=None, ge=0, le=10)
    high_windows: bool | None = None
    #: Facades in glass, counted from the front.
    glazed_sides: int | None = Field(default=None, ge=0, le=4)
    open_sides: bool | None = None
    louvers: bool | None = None
    mesh_doors: bool | None = None
    transformer_yard: bool | None = None
    tank_lid: bool | None = None
