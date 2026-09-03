"""Generate conservative Version 1 WPS/WRF namelist starting points."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

from weather_sim.config.models import DomainConfig, ExperimentConfig


def _values(values: list[object], quote: bool = False) -> str:
    if quote:
        return ", ".join(f"'{value}'" for value in values) + ","
    formatted = []
    for value in values:
        if isinstance(value, bool):
            formatted.append(".true." if value else ".false.")
        else:
            formatted.append(str(value))
    return ", ".join(formatted) + ","


def _dates(config: ExperimentConfig) -> tuple[datetime, datetime]:
    return config.time.simulation_start_utc.replace(tzinfo=None), config.time.target_end_utc.replace(tzinfo=None)


def _parent_start(parent: DomainConfig, child: DomainConfig) -> tuple[int, int]:
    child_parent_intervals_x = (child.e_we - 1) // child.parent_grid_ratio
    child_parent_intervals_y = (child.e_sn - 1) // child.parent_grid_ratio
    return (
        max(1, (parent.e_we - child_parent_intervals_x) // 2),
        max(1, (parent.e_sn - child_parent_intervals_y) // 2),
    )


def render_namelist_wps(config: ExperimentConfig, geog_data_path: str) -> str:
    domains = config.domains
    start, end = _dates(config)
    start_text = start.strftime("%Y-%m-%d_%H:%M:%S")
    end_text = end.strftime("%Y-%m-%d_%H:%M:%S")
    starts = [(1, 1)] + [_parent_start(domains[i - 1], domains[i]) for i in range(1, len(domains))]
    return f"""&share
 wrf_core = 'ARW',
 max_dom = {len(domains)},
 start_date = {_values([start_text] * len(domains), quote=True)}
 end_date = {_values([end_text] * len(domains), quote=True)}
 interval_seconds = {config.wrf.input_interval_seconds},
/

&geogrid
 parent_id = {_values([0] + list(range(1, len(domains))))}
 parent_grid_ratio = {_values([1] + [d.parent_grid_ratio for d in domains[1:]])}
 i_parent_start = {_values([value[0] for value in starts])}
 j_parent_start = {_values([value[1] for value in starts])}
 e_we = {_values([d.e_we for d in domains])}
 e_sn = {_values([d.e_sn for d in domains])}
 geog_data_res = {_values(['default'] * len(domains), quote=True)}
 dx = {domains[0].dx_m},
 dy = {domains[0].dx_m},
 map_proj = 'lambert',
 ref_lat = {config.center.latitude},
 ref_lon = {config.center.longitude},
 truelat1 = {config.center.latitude},
 truelat2 = {config.center.latitude},
 stand_lon = {config.center.longitude},
 geog_data_path = '{geog_data_path}',
/

&ungrib
 out_format = 'WPS',
 prefix = 'FILE',
/

&metgrid
 fg_name = 'FILE',
 io_form_metgrid = 2,
/
"""


def render_namelist_input(config: ExperimentConfig) -> str:
    domains = config.domains
    start, end = _dates(config)
    count = len(domains)
    run = end - start
    starts = [(1, 1)] + [_parent_start(domains[i - 1], domains[i]) for i in range(1, count)]
    fields = lambda value: _values([value] * count)
    return f"""&time_control
 run_days = {run.days},
 run_hours = {run.seconds // 3600},
 run_minutes = {(run.seconds % 3600) // 60},
 start_year = {fields(start.year)}
 start_month = {fields(start.month)}
 start_day = {fields(start.day)}
 start_hour = {fields(start.hour)}
 start_minute = {fields(start.minute)}
 start_second = {fields(start.second)}
 end_year = {fields(end.year)}
 end_month = {fields(end.month)}
 end_day = {fields(end.day)}
 end_hour = {fields(end.hour)}
 end_minute = {fields(end.minute)}
 end_second = {fields(end.second)}
 interval_seconds = {config.wrf.input_interval_seconds},
 input_from_file = {_values([True] * count)}
 history_interval = {fields(config.analysis.output_interval_minutes)}
 frames_per_outfile = {fields(6)}
 restart = .false.,
 io_form_history = 2,
 io_form_restart = 2,
 io_form_input = 2,
 io_form_boundary = 2,
/

&domains
 time_step = {config.wrf.time_step_seconds},
 max_dom = {count},
 e_we = {_values([d.e_we for d in domains])}
 e_sn = {_values([d.e_sn for d in domains])}
 e_vert = {fields(config.wrf.vertical_levels)}
 dx = {_values([d.dx_m for d in domains])}
 dy = {_values([d.dx_m for d in domains])}
 grid_id = {_values(list(range(1, count + 1)))}
 parent_id = {_values([0] + list(range(1, count)))}
 i_parent_start = {_values([value[0] for value in starts])}
 j_parent_start = {_values([value[1] for value in starts])}
 parent_grid_ratio = {_values([1] + [d.parent_grid_ratio for d in domains[1:]])}
 parent_time_step_ratio = {_values([1] + [d.parent_grid_ratio for d in domains[1:]])}
 feedback = 1,
 smooth_option = 0,
/

&physics
 mp_physics = {_values([8] * count)}
 ra_lw_physics = {_values([4] * count)}
 ra_sw_physics = {_values([4] * count)}
 radt = {_values([15] * count)}
 sf_sfclay_physics = {_values([1] * count)}
 sf_surface_physics = {_values([2] * count)}
 bl_pbl_physics = {_values([1] * count)}
 bldt = {_values([0] * count)}
 cu_physics = {_values([1] + [0] * (count - 1))}
 cudt = {_values([5] + [0] * (count - 1))}
 num_soil_layers = 4,
 num_land_cat = 21,
/

&dynamics
 hybrid_opt = 2,
 w_damping = 1,
 diff_opt = 2,
 km_opt = 4,
 damp_opt = 3,
 zdamp = 5000.,
 dampcoef = 0.2,
 non_hydrostatic = {_values([True] * count)}
 moist_adv_opt = {_values([1] * count)}
 scalar_adv_opt = {_values([1] * count)}
/

&bdy_control
 spec_bdy_width = 5,
 specified = {_values([True] + [False] * (count - 1))}
 nested = {_values([False] + [True] * (count - 1))}
/

&namelist_quilt
 nio_tasks_per_group = 0,
 nio_groups = 1,
/
"""


def write_namelists(config: ExperimentConfig, output_dir: str | Path, geog_data_path: str) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    wps_path = target / "namelist.wps"
    input_path = target / "namelist.input"
    wps_path.write_text(render_namelist_wps(config, geog_data_path), encoding="utf-8")
    input_path.write_text(render_namelist_input(config), encoding="utf-8")
    return wps_path, input_path
