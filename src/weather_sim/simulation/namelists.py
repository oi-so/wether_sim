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
    return config.simulation_start_utc.replace(tzinfo=None), config.simulation_end_utc.replace(tzinfo=None)


def _parent_start(parent: DomainConfig, child: DomainConfig) -> tuple[int, int]:
    # WPS indices are one-based. Align the geometric centres of parent and
    # child; using integer interval counts here shifts each nested domain by
    # roughly half a parent cell and compounds across nesting levels.
    parent_center_x = (parent.e_we + 1) / 2
    parent_center_y = (parent.e_sn + 1) / 2
    child_half_span_x = (child.e_we - 1) / (2 * child.parent_grid_ratio)
    child_half_span_y = (child.e_sn - 1) / (2 * child.parent_grid_ratio)
    return (
        max(1, round(parent_center_x - child_half_span_x)),
        max(1, round(parent_center_y - child_half_span_y)),
    )


def render_namelist_wps(
    config: ExperimentConfig,
    geog_data_path: str,
    *,
    ungrib_prefix: str = "FILE",
    metgrid_sources: tuple[str, ...] = ("FILE",),
) -> str:
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
 prefix = '{ungrib_prefix}',
 ordered_by_date = .false.,
/

&metgrid
 fg_name = {_values(list(metgrid_sources), quote=True)}
 io_form_metgrid = 2,
/
"""


def render_namelist_input(config: ExperimentConfig) -> str:
    domains = config.domains
    start, end = _dates(config)
    count = len(domains)
    # real.exe needs the bracketing input time, whereas wrf.exe gives run_*
    # precedence and can finish at the requested analysis end.
    run = config.time.target_end_utc.replace(tzinfo=None) - start
    starts = [(1, 1)] + [_parent_start(domains[i - 1], domains[i]) for i in range(1, count)]
    fields = lambda value: _values([value] * count)
    history_intervals = [
        config.analysis.parent_output_interval_minutes or config.analysis.output_interval_minutes
    ] * (count - 1) + [config.analysis.output_interval_minutes]
    # WRF Registry declares gfdda_end_h INTEGER. It describes the last
    # analysis, including the bracketing input after the integration end.
    fdda_end_hours = int((end - start).total_seconds() + 3599) // 3600
    pbl_switch = 0 if config.wrf.grid_nudging_in_pbl else 1
    fdda = ""
    if config.wrf.grid_nudging:
        fdda = f"""
&fdda
 grid_fdda = {fields(1)}
 gfdda_inname = 'wrffdda_d<domain>',
 gfdda_interval_m = {fields(config.wrf.input_interval_seconds // 60)}
 gfdda_end_h = {fields(fdda_end_hours)}
 io_form_gfdda = 2,
 fgdt = {fields(0)}
 if_no_pbl_nudging_uv = {fields(pbl_switch)}
 if_no_pbl_nudging_t = {fields(pbl_switch)}
 if_no_pbl_nudging_q = {fields(pbl_switch)}
 if_zfac_uv = {fields(0)}
 if_zfac_t = {fields(0)}
 if_zfac_q = {fields(0)}
 guv = {fields(config.wrf.nudging_uv_s)}
 gt = {fields(config.wrf.nudging_temperature_s)}
 gq = {fields(config.wrf.nudging_moisture_s)}
 if_ramping = 0,
 dtramp_min = 0.0,
/
"""
    return f"""&time_control
 run_days = {run.days},
 run_hours = {run.seconds // 3600},
 run_minutes = {(run.seconds % 3600) // 60},
 run_seconds = {run.seconds % 60},
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
 history_interval = {_values(history_intervals)}
 frames_per_outfile = {fields(1000)}
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
 num_metgrid_levels = {config.wrf.metgrid_levels},
 num_metgrid_soil_levels = {config.wrf.metgrid_soil_levels},
 p_top_requested = {config.wrf.top_pressure_pa},
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
 swint_opt = {config.wrf.shortwave_interpolation},
 sf_sfclay_physics = {_values([1] * count)}
 sf_surface_physics = {_values([2] * count)}
 sf_urban_physics = {_values([config.wrf.urban_physics] * count)}
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
{fdda}
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


def write_namelists(
    config: ExperimentConfig,
    output_dir: str | Path,
    geog_data_path: str,
    *,
    ungrib_prefix: str = "FILE",
    metgrid_sources: tuple[str, ...] = ("FILE",),
) -> tuple[Path, Path]:
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    wps_path = target / "namelist.wps"
    input_path = target / "namelist.input"
    wps_path.write_text(
        render_namelist_wps(
            config,
            geog_data_path,
            ungrib_prefix=ungrib_prefix,
            metgrid_sources=metgrid_sources,
        ),
        encoding="utf-8",
    )
    input_path.write_text(render_namelist_input(config), encoding="utf-8")
    return wps_path, input_path
