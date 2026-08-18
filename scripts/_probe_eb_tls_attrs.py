"""
Probe script: check TLS secondary depth and all results attributes.
Run as: .venv/bin/python scripts/_probe_eb_tls_attrs.py
"""
import multiprocessing
import time
import numpy as np
from astropy.io import fits
from wotan import flatten
from transitleastsquares import transitleastsquares as TLS

if __name__ == "__main__":
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

    # Use single thread for narrow range to get result quickly  
    model = TLS(t, flat_f)
    # Use narrow range 
    res = model.power(period_min=2.5, period_max=2.55,
                      use_threads=1, show_progress_bar=False)
    
    print("All scalar TLS result attributes:")
    for attr in sorted(dir(res)):
        if attr.startswith('_'):
            continue
        val = getattr(res, attr, None)
        if callable(val):
            continue
        if isinstance(val, (float, int, str, bool)) or (hasattr(val, 'item') and val.ndim == 0):
            try:
                print(f"  {attr} = {float(val) if not isinstance(val, str) else val!r}")
            except:
                pass
        elif hasattr(val, '__len__') and len(val) <= 5:
            print(f"  {attr} = {list(val)}")
