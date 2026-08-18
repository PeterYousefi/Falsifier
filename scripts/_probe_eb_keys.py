"""
Probe: dump all dict keys in TLS result.
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
    
    print("All dict keys in TLS result:")
    for k in sorted(res.keys()):
        v = res[k]
        if isinstance(v, (int, float, str, bool)):
            print(f"  {k!r}: {v}")
        elif hasattr(v, 'ndim'):
            if v.ndim == 0:
                print(f"  {k!r}: {float(v)} (scalar ndarray)")
            else:
                print(f"  {k!r}: array shape {v.shape}, first few: {v[:3] if len(v) >= 3 else v}")
        elif isinstance(v, list):
            print(f"  {k!r}: list len={len(v)}, first: {v[:3]}")
        else:
            print(f"  {k!r}: {type(v).__name__}")

if __name__ == "__main__":
    main()
