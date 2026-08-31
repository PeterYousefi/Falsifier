"""
falsifier.utils
===============
Standalone numerical and math utility helpers shared across the falsifier package.

These functions carry no external dependencies beyond the Python standard library.
"""

from __future__ import annotations

__all__ = ["assert_relative_tolerance"]


def assert_relative_tolerance(
    actual: float,
    expected: float,
    rtol: float = 1e-5,
    atol: float = 1e-8,
) -> bool:
    """Check whether *actual* is within a combined relative + absolute tolerance of *expected*.

    The comparison follows the same convention as :func:`math.isclose` and
    :func:`numpy.testing.assert_allclose`::

        |actual - expected| <= atol + rtol * |expected|

    Parameters
    ----------
    actual:
        The value produced by the code under test or by the pipeline.
    expected:
        The reference (ground-truth) value.
    rtol:
        Relative tolerance — scales with the magnitude of *expected*.
        Defaults to ``1e-5``.
    atol:
        Absolute tolerance — applied regardless of magnitude, guarding against
        false failures near zero.  Defaults to ``1e-8``.

    Returns
    -------
    bool
        ``True`` if *actual* is within the combined tolerance of *expected*,
        ``False`` otherwise.

    Examples
    --------
    >>> assert_relative_tolerance(1.000009, 1.0)
    True
    >>> assert_relative_tolerance(1.1, 1.0, rtol=0.05)
    False
    >>> assert_relative_tolerance(0.0, 0.0)
    True
    """
    return abs(actual - expected) <= atol + rtol * abs(expected)
