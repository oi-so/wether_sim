import numpy as np
import pytest
from weather_sim.visualization.composite import MeshBlend, interpolate_time, interval_rain


def grid(radius, count):
    x,y=np.meshgrid(np.linspace(-radius,radius,count),np.linspace(-radius,radius,count))
    return np.column_stack([x.ravel(),y.ravel()])


def test_nested_mesh_has_shared_vertices_and_preserves_linear_field():
    points=[grid(10,7),grid(5,9),grid(2,11)]
    plan=MeshBlend(points,[3,2,1])
    values=[3*p[:,0]+2*p[:,1]+7 for p in points]
    np.testing.assert_allclose(plan.blend(values),3*plan.points[:,0]+2*plan.points[:,1]+7,atol=1e-10)
    triangles=plan.triangles
    edges=np.sort(np.concatenate([triangles[:,[0,1]],triangles[:,[1,2]],triangles[:,[2,0]]]),axis=1)
    _,count=np.unique(edges,axis=0,return_counts=True)
    assert np.all((count==1)|(count==2))
    assert len(np.unique(plan.points,axis=0))==len(plan.points)
    # Fine-domain edge is entirely parent-valued; the center is finest-valued.
    mixed=plan.blend([np.full(len(p),value) for p,value in zip(points,[0,10,20])])
    center=np.argmin(np.linalg.norm(plan.points,axis=1))
    assert mixed[center]==pytest.approx(20)
    edge=(np.isclose(np.abs(plan.points[:,0]),2)&np.isclose(plan.points[:,1],0))
    np.testing.assert_allclose(mixed[edge],10,atol=1e-10)


def test_common_rain_is_conservative_and_never_invents_missing_intervals():
    times=np.arange(0,7201,600.)
    rates=np.full((len(times),1),6.)
    amount=interval_rain(rates,times,np.full(len(times),1/6),np.array([0.,3600,7200]))
    np.testing.assert_allclose(amount[:,0],[np.nan,6,6])
    rates[3]=np.nan
    assert np.isnan(interval_rain(rates,times,np.full(len(times),1/6),np.array([0.,3600,7200]))[1,0])
    with pytest.raises(ValueError,match='outside'):
        interpolate_time(np.array([[1.],[2.]]),np.array([0.,1.]),np.array([2.]))
    np.testing.assert_allclose(interpolate_time(np.array([[1.],[3.]]),np.array([0.,1.]),np.array([0.,.5,1.])),[[1],[2],[3]])
