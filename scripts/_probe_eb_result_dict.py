"""
Probe: dump all TLS result fields.
"""
import multiprocessing
import time
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

    n_threads = multiprocessing.cpu_count()
    model = TLS(t, flat_f)
    res = model.power(period_min=1.0, period_max=10.0,
                      use_threads=n_threads, show_progress_bar=False)
    
    # Try to access result as dict or namespace
    print("Type:", type(res))
    print("Dir:", [x for x in dir(res) if not x.startswith('_')])
    if hasattr(res, '__dict__'):
        for k, v in res.__dict__.items():
            try:
                if isinstance(v, (int, float, str, bool)):
                    print(f"  {k}: {v}")
                elif isinstance(v, np.ndarray) and v.ndim == 0:
                    print(f"  {k}: {float(v)}")
            except:
                pass
    
    # Access specific candidates
    for attr in ['secondary_depth', 'secondary', 'secondary_eclipse_depth',
                 'transit_times', 'transit_depths', 'per_transit_count',
                 'odd_even_mismatch', 'depth', 'depth_mean', 'depth_r', 'depth_even', 'depth_odd']:
        v = getattr(res, attr, 'MISSING')
        if v != 'MISSING':
            try:
                if hasattr(v, '__len__') and len(v) < 50:
                    print(f"  {attr}: {list(v)[:10]} (len={len(v)})")
                else:
                    print(f"  {attr}: {v}")
            except:
                print(f"  {attr}: (error accessing)")

if __name__ == "__main__":
    main()
