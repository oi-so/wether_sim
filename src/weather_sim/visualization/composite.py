"""Display-only nested-domain mosaic with a shared triangulation and feathered seams."""
from __future__ import annotations

import base64
import json
import re
from pathlib import Path

import numpy as np
import pandas as pd
from matplotlib.tri import Triangulation

from weather_sim.visualization.volume import _packed
from weather_sim.visualization.fields import field_limits


def unpack(value):
    return np.frombuffer(base64.b64decode(value), dtype='<f4')


def read_payload(path: Path) -> dict:
    match = re.search(r'<script id="data" type="application/json">([\s\S]*?)</script>', path.read_text())
    if match is None:
        raise ValueError(f'WRF payload missing: {path}')
    return json.loads(match.group(1))


def write_payload(data: dict, path: Path) -> Path:
    template = Path(__file__).with_name('volume_viewer.html').read_text()
    text = json.dumps(data, ensure_ascii=False).replace('</', '<\\/')
    temp = path.with_suffix('.html.tmp')
    temp.write_text(template.replace('__WRF_DATA__', text))
    temp.replace(path)
    summary = {k: data[k] for k in ['source_domain', 'shape', 'times', 'scales', 'center', 'radius_km']}
    summary.update(bytes=path.stat().st_size, method=data.get('composite_note'), terrain_shape=data['terrain']['shape'])
    path.with_suffix('.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    return path


class Delaunay:
    """Use Matplotlib's bundled triangulator without a new SciPy dependency."""
    def __init__(self, points):
        self.mesh = Triangulation(points[:,0], points[:,1])
        self.simplices = self.mesh.triangles
        self.finder = self.mesh.get_trifinder()
        corners = points[self.simplices]
        matrix = np.stack([corners[:,0]-corners[:,2],corners[:,1]-corners[:,2]],axis=-1)
        self.transform = np.concatenate([np.linalg.inv(matrix),corners[:,2,None,:]],axis=1)

    def find_simplex(self, points, tol=None):
        return self.finder(points[:,0],points[:,1])


def hull_equations(points):
    """Convex hull half-planes from a monotone-chain hull in local km."""
    ordered = sorted(set(map(tuple,points)))
    def cross(o,a,b):
        return (a[0]-o[0])*(b[1]-o[1])-(a[1]-o[1])*(b[0]-o[0])
    def chain(items):
        result=[]
        for p in items:
            while len(result)>=2 and cross(result[-2],result[-1],p)<=0:result.pop()
            result.append(p)
        return result
    hull=np.asarray(chain(ordered)[:-1]+chain(reversed(ordered))[:-1])
    edge=np.roll(hull,-1,axis=0)-hull
    normal=np.column_stack([edge[:,1],-edge[:,0]])
    normal/=np.linalg.norm(normal,axis=1)[:,None]
    return np.column_stack([normal,-np.sum(normal*hull,axis=1)])


class MeshBlend:
    """One conforming mesh; finer grids replace covered coarse vertices."""
    def __init__(self, points: list[np.ndarray], widths: list[float]):
        self.sources = [Delaunay(p) for p in points]
        merged = points[0]
        for p, triangulation in zip(points[1:], self.sources[1:]):
            merged = np.concatenate([merged[triangulation.find_simplex(merged) < 0], p])
        self.points = merged
        self.triangles = Delaunay(merged).simplices.astype('<u4')
        self.plans = []
        self.weights = []
        for i, (p, tri) in enumerate(zip(points, self.sources)):
            simplex = tri.find_simplex(merged, tol=1e-8)
            inside = simplex >= 0
            safe = np.maximum(simplex, 0)
            transform = tri.transform[safe]
            bary = np.einsum('nij,nj->ni', transform[:, :2], merged-transform[:, 2])
            bary = np.column_stack([bary, 1-bary.sum(axis=1)])
            self.plans.append((tri.simplices[safe], bary, inside))
            if i == 0:
                if not inside.all():
                    raise ValueError('child mesh extends beyond parent mesh')
                weight = np.ones(len(merged))
            else:
                equations = hull_equations(p)
                # Hull equations have unit normals; distance is in local km.
                distance = -(merged @ equations[:, :2].T + equations[:, 2]).max(axis=1)
                weight = np.where(inside, np.clip(distance / widths[i], 0, 1), 0)
                weight = weight*weight*(3-2*weight)  # Continuous value and slope at band edges.
            self.weights.append(weight)

    def sample(self, values, index):
        ids, bary, inside = self.plans[index]
        selected = np.asarray(values)[..., ids]
        # Zero-weight missing neighbors must not erase a valid exact grid vertex.
        result = np.sum(np.where(np.abs(bary)>1e-12, selected*bary, 0), axis=-1)
        return np.where(inside, result, np.nan)

    def blend(self, values: list[np.ndarray]) -> np.ndarray:
        result = self.sample(values[0], 0)
        for i in range(1, len(values)):
            fine = self.sample(values[i], i)
            w = self.weights[i]
            result = np.where(w <= 1e-12, result, np.where(w >= 1-1e-12, fine, (1-w)*result+w*fine))
        return result


def interpolate_time(values, source, target):
    """Linear display interpolation within the source period; never extrapolate."""
    if target[0] < source[0]-1e-6 or target[-1] > source[-1]+1e-6:
        raise ValueError('composite time lies outside a source domain')
    if len(source)==1:
        return np.broadcast_to(values[0], (len(target),)+values.shape[1:]).copy()
    right = np.clip(np.searchsorted(source, target, side='right'), 1, len(source)-1)
    left = right-1
    weight = (target-source[left])/(source[right]-source[left])
    weight = weight.reshape((-1,)+(1,)*(values.ndim-1))
    return np.where(weight<=1e-12, values[left], np.where(weight>=1-1e-12, values[right], values[left]*(1-weight)+values[right]*weight))


def interval_rain(rate, source, hours, target):
    """Integrate native interval means over common intervals; missing stays missing."""
    result = np.full((len(target),)+rate.shape[1:], np.nan)
    starts = source-np.asarray(hours,dtype=float)*3600
    for i in range(1, len(target)):
        overlap = np.maximum(0, np.minimum(source, target[i])-np.maximum(starts, target[i-1]))
        use = overlap>1e-6
        if not use.any() or not np.isclose(overlap[use].sum(), target[i]-target[i-1], atol=.05, rtol=0):
            continue
        shape=(-1,)+(1,)*(rate.ndim-1)
        result[i] = np.sum(rate[use]*overlap[use].reshape(shape)/3600,axis=0)
    return result


def create_composite_animation(paths: list[Path], output: Path) -> Path:
    """Read generated d01/d02/d03 payloads, keeping original HTMLs independent."""
    domains = [read_payload(path) for path in paths]
    if [d['source_domain'] for d in domains] != ['d01','d02','d03']:
        raise ValueError('composite requires d01, d02, d03 in coarse-to-fine order')
    if len({d['shape'][1] for d in domains})!=1 or any(d['center']!=domains[0]['center'] for d in domains):
        raise ValueError('composite domains need matching center and sampled vertical levels')
    clocks = [pd.DatetimeIndex(pd.to_datetime(d['times'],format='%Y/%m/%d %H:%M:%S JST')).tz_localize('Asia/Tokyo').tz_convert('UTC') for d in domains]
    start=max(t[0] for t in clocks).ceil('h');end=min(t[-1] for t in clocks).floor('h')
    times=pd.date_range(start,end,freq='h')
    if len(times)<2:
        raise ValueError('composite needs at least two common hourly frames')
    source_times=[t.as_unit('ns').asi8/1e9 for t in clocks]; target_times=times.as_unit('ns').asi8/1e9
    volume_points=[np.column_stack([unpack(d['xy'][0]),unpack(d['xy'][1])]) for d in domains]
    surface_points=[np.column_stack([unpack(d['terrain']['x']),unpack(d['terrain']['y'])]) for d in domains]
    widths=[float(d['dx_km'])*3 for d in domains]
    vp=MeshBlend(volume_points,widths);sp=MeshBlend(surface_points,widths)
    fields={}
    for name in domains[0]['fields']:
        values=[interpolate_time(unpack(d['fields'][name]).reshape(d['shape']).reshape(d['shape'][0],d['shape'][1],-1),s,target_times) for d,s in zip(domains,source_times)]
        fields[name]=_packed(vp.blend(values))
    surface={};amounts=[]
    for d,s in zip(domains,source_times):
        rate=unpack(d['surface']['fields']['precipitation']).reshape(d['shape'][0],-1)
        hours=d.get('interval_hours')
        if hours is None:
            hours=np.r_[np.nan,np.diff(s)/3600]
        amounts.append(interval_rain(rate,s,hours,target_times))
    for name in domains[0]['surface']['fields']:
        if name in {'precipitation','precipitation_interval'}:
            # Common frames are hourly: amount in mm equals mean mm/h numerically.
            merged=sp.blend(amounts)
        else:
            values=[interpolate_time(unpack(d['surface']['fields'][name]).reshape(d['shape'][0],-1),s,target_times) for d,s in zip(domains,source_times)]
            merged=sp.blend(values)
        surface[name]=_packed(merged)
    base=domains[0]
    terrain={key:_packed(sp.blend([unpack(d['terrain'][key]) for d in domains])) for key in ['z','lat','lon']}
    terrain.update(shape=[1,len(sp.points)],x=_packed(sp.points[:,0]),y=_packed(sp.points[:,1]),triangles=base64.b64encode(sp.triangles.tobytes()).decode())
    texture=base['terrain'].get('texture')
    if texture:
        texture=dict(texture)
        uv=unpack(texture['uv']).reshape(-1,2)
        texture['uv']=_packed(sp.sample(uv.T,0).T)
    terrain['texture']=texture
    latlon=[_packed(vp.blend([unpack(d['latlon'][i]) for d in domains])) for i in range(2)]
    result={k:v for k,v in base.items() if k not in {'fields','terrain','surface','latlon','xy','shape','times','domain_links'}}
    result.update(source_domain='combined',dx_km=9,shape=[len(times),base['shape'][1],1,len(vp.points)],
                  fields=fields,terrain=terrain,latlon=latlon,xy=[_packed(vp.points[:,0]),_packed(vp.points[:,1])],
                  triangles=base64.b64encode(vp.triangles.tobytes()).decode(),times=[t.tz_convert('Asia/Tokyo').strftime('%Y/%m/%d %H:%M:%S JST') for t in times],
                  surface={**base['surface'],'fields':surface},interval_hours=[None]+[1.]*(len(times)-1),
                  domain_links={'combined':'atmosphere_combined.html','d03':'atmosphere_3d.html','d02':'d02/atmosphere_3d.html','d01':'d01/atmosphere_3d.html'},
                  composite_note='統合表示専用：毎時の共通時刻へ補間、境界は子領域3格子幅で連続接続。雨は共通1時間区間へ積分（最初の雨は欠測）。各領域の元値は個別表示で確認。地図は広域用。')
    for name in result['variables']:
        values=unpack(fields[name]);finite=values[np.isfinite(values)]
        if name not in {'humidity','CLDFRA'} and finite.size:
            low,high=float(finite.min()),float(finite.max())
            if name=='W':high=max(abs(low),abs(high),.01);low=-high
            result['scales'][name]=[low,max(high,low+1e-6)]
    for name in result['surface']['variables']:
        if name not in {'humidity','cloud_total','cloud_low','cloud_mid','cloud_high','precipitation','precipitation_interval'}:
            result['surface']['scales'][name]=field_limits(unpack(surface[name]),zero_based=name in {'wind','cloud_water_path','cloud_ice_path'})
    result['surface']['variables']['precipitation_interval']=['共通1時間の降水量','降水量（mm/1時間・表示補間）']
    return write_payload(result,output)
