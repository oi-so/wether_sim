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


def test_fdda_case_enables_three_hourly_grid_nudging() -> None:
    text = render_namelist_input(load_config("config/case_20260904_fdda.yaml"))
    assert "&fdda" in text
    assert "grid_fdda = 1, 1, 1," in text
    assert "gfdda_interval_m = 180, 180, 180," in text
    assert "if_no_pbl_nudging_t = 0, 0, 0," in text
    assert "gt = 0.0003, 0.0003, 0.0003," in text


def test_efficient_case_preserves_boundary_bracket_and_inner_output() -> None:
    config = load_config("config/case_20260904_fdda_efficient.yaml")
    wrf = render_namelist_input(config)
    wps = render_namelist_wps(config, "/opt/WPS_GEOG")
    assert "run_hours = 14," in wrf
    assert "end_hour = 12, 12, 12," in wrf  # real.exe still prepares 21 JST input
    assert "2026-09-04_12:00:00" in wps
    assert "history_interval = 60, 60, 10," in wrf
    assert "gfdda_end_h = 15, 15, 15," in wrf
    assert "grid_fdda = 1, 1, 1," in wrf


def test_runtime_keeps_seconds_at_unaligned_end() -> None:
    from dataclasses import replace
    from datetime import timedelta
    config = load_config("config/case_20260904.yaml")
    config = replace(config, time=replace(config.time, target_end=config.time.target_end + timedelta(seconds=35)))
    assert "run_seconds = 35," in render_namelist_input(config)


def test_default_cli_profile_applies_msm_nudging_and_parent_output_reduction() -> None:
    from weather_sim.cli import _parser
    args = _parser().parse_args(["run-case", "--start", "2026-09-04 12:00", "--end", "2026-09-04 20:00"])
    text = render_namelist_input(load_config(args.template))
    assert "grid_fdda = 1, 1, 1," in text
    assert "history_interval = 60, 60, 10," in text
    assert "gfdda_end_h = 15, 15, 15," in text
