"""
Probe: get all TLS scalar attributes for the EB golden data at the known period.
Run as: .venv/bin/python scripts/_probe_eb_tls_attrs2.py
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
    print(f"Using {n_threads} threads")

    t0 = time.monotonic()
    model = TLS(t, flat_f)
    # Narrow search around 2.54 to get quick result
    res = model.power(period_min=2.52, period_max=2.56,
                      use_threads=n_threads, show_progress_bar=False)
    elapsed = time.monotonic() - t0
    print(f"Elapsed: {elapsed:.2f}s")

    print("\nAll scalar TLS result attributes:")
    for attr in sorted(dir(res)):
        if attr.startswith('_'):
            continue
        val = getattr(res, attr, None)
        if callable(val):
            continue
        if isinstance(val, (float, int, str, bool)):
            print(f"  {attr} = {val!r}")
        elif hasattr(val, 'ndim') and val.ndim == 0:
            print(f"  {attr} = {float(val)!r}")
        elif hasattr(val, '__len__') and 1 <= len(val) <= 5:
            print(f"  {attr} = {list(val)}")

if __name__ == "__main__":
    main()
