"""
Probe: depth_mean_odd and depth_mean_even for EB golden data.
"""
import multiprocessing
import numpy as np
from astropy.io import fits
from wotan import flatten

def main():
    from transitleastsquares import transitleastsquares as TLS

    with fits.open('data/golden/kic6965293_q3_long.fits') as hdul:
        t = hdul[1].data['TIME'].astype(np.float64)
        f = hdul[1].data['FLUX'].astype(np.float64)
        q = hdul[1].data['QUALITY'].astype(np.int32)

    mask = np.isfinite(t) & np.isfinite(f) & (q == 0)
    t, f = t[mask], f[mask]
    f /= np.median(f)

    flat_f, _ = flatten(t, f, method='biweight', window_length=2.0,
                        break_tolerance=0.5, edge_cutoff=0, return_trend=True, cval=5.0)
    flat_f = np.where(np.isfinite(flat_f), flat_f, 1.0)

    model = TLS(t, flat_f)
    res = model.power(period_min=1.0, period_max=10.0,
                      use_threads=multiprocessing.cpu_count(), show_progress_bar=False)
    
    print(f"period={res.period:.5f}d")
    print(f"depth_mean = {res.depth_mean}")  # (mean, uncertainty)
    print(f"depth_mean_odd = {res.depth_mean_odd}")
    print(f"depth_mean_even = {res.depth_mean_even}")
    print(f"odd_even_mismatch = {res.odd_even_mismatch:.4f}")
    print()
    # depth_mean is (mean, uncertainty) where mean = 1 - transit_depth
    # So depth = 1 - depth_mean[0]
    depth_m = res.depth_mean
    depth_odd = res.depth_mean_odd
    depth_even = res.depth_mean_even
    print(f"Primary depth (1-depth_mean[0]) = {(1-depth_m[0])*1e6:.0f} ppm")
    print(f"Odd depth (1-odd[0]) = {(1-depth_odd[0])*1e6:.0f} ppm ± {depth_odd[1]*1e6:.0f} ppm")
    print(f"Even depth (1-even[0]) = {(1-depth_even[0])*1e6:.0f} ppm ± {depth_even[1]*1e6:.0f} ppm")
    
    odd_depth_ppm = (1 - depth_odd[0]) * 1e6
    even_depth_ppm = (1 - depth_even[0]) * 1e6
    odd_unc = depth_odd[1] * 1e6
    even_unc = depth_even[1] * 1e6
    
    if odd_depth_ppm > even_depth_ppm:
        deeper, shallower, deeper_unc, shallower_unc = odd_depth_ppm, even_depth_ppm, odd_unc, even_unc
    else:
        deeper, shallower, deeper_unc, shallower_unc = even_depth_ppm, odd_depth_ppm, even_unc, odd_unc
    
    depth_diff = deeper - shallower
    quadrature_unc = np.sqrt(deeper_unc**2 + shallower_unc**2)
    sigma = depth_diff / quadrature_unc if quadrature_unc > 0 else 0
    ratio = deeper / shallower if shallower > 0 else float('inf')
    
    print(f"\nDirect calculation:")
    print(f"  Depth difference: {depth_diff:.0f} ppm")
    print(f"  Quadrature uncertainty: {quadrature_unc:.0f} ppm")
    print(f"  Significance (sigma): {sigma:.2f}")
    print(f"  Depth ratio (deeper/shallower): {ratio:.2f}")
    print(f"  TLS odd_even_mismatch: {res.odd_even_mismatch:.4f}")
    
    # Also look at transit_depths to understand variability
    td = res.transit_depths
    td_ppm = (1 - td) * 1e6
    print(f"\ntransit_depths (ppm), first 10:")
    for i, d in enumerate(td_ppm[:10]):
        print(f"  transit {i}: {d:.0f} ppm ({'odd' if i%2==0 else 'even'})")

if __name__ == "__main__":
    main()
