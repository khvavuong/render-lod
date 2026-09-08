import pytest
from pydantic import ValidationError

from v365_archviz.domain.design import FacadeArticulation, FacadeDesign, LoadingDock


def test_facade_rejects_duplicate_dock_ids() -> None:
    with pytest.raises(ValidationError, match="loading dock IDs"):
        FacadeDesign(
            surface_id="factory-a:south",
            panel_module_m=1.0,
            loading_docks=(
                LoadingDock(dock_id="dock-01", u=0.2, width_m=4.2),
                LoadingDock(dock_id="dock-01", u=0.4, width_m=4.2),
            ),
        )


def test_loading_dock_must_be_on_surface_interval() -> None:
    with pytest.raises(ValidationError):
        LoadingDock(dock_id="dock-01", u=1.1, width_m=4.2)


def test_facade_articulation_rejects_impossible_glazing_ratio() -> None:
    with pytest.raises(ValidationError):
        FacadeArticulation(office_glazing_ratio=1.1)
