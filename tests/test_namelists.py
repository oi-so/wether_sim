from weather_sim.config import load_config
from weather_sim.simulation.namelists import render_namelist_input, render_namelist_wps


def test_wps_namelist_contains_three_nested_domains() -> None:
    text = render_namelist_wps(load_config("config/default.yaml"), "/opt/WPS_GEOG")
    assert "max_dom = 3" in text
    assert "parent_grid_ratio = 1, 3, 3," in text
    assert "i_parent_start = 1, 34, 34," in text
    assert "j_parent_start = 1, 34, 34," in text
    assert "e_we = 100, 100, 100," in text
    assert "geog_data_path = '/opt/WPS_GEOG'" in text


def test_wrf_namelist_uses_spinup_start_and_output_interval() -> None:
    text = render_namelist_input(load_config("config/default.yaml"))
    assert "start_day = 9, 9, 9," in text
    assert "start_hour = 15, 15, 15," in text
    assert "history_interval = 10, 10, 10," in text
    assert "cu_physics = 1, 0, 0," in text


def test_msm_case_declares_input_vertical_dimensions() -> None:
    text = render_namelist_input(load_config("config/case_20260901.yaml"))
    assert "num_metgrid_levels = 17," in text
    assert "num_metgrid_soil_levels = 4," in text
    assert "p_top_requested = 10000," in text
