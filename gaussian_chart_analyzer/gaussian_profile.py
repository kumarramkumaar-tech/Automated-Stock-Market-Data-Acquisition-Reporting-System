"""
gaussian_profile.py - Gaussian Bell Curve fitting and gap analysis for Volume Profile data.

Given volume-at-price data extracted from a chart, this module:
1. Fits a Gaussian (normal) distribution curve to the volume data
2. Identifies the ideal bell curve shape
3. Calculates the volume gap at each price level
   (how much volume needs to be added to match the Gaussian profile)
4. Provides statistical metrics (mean, std, skewness, kurtosis)
"""

import numpy as np
import pandas as pd
from scipy import stats
from scipy.optimize import curve_fit
from dataclasses import dataclass, field
from typing import List, Tuple, Optional


@dataclass
class GaussianResult:
    """Results of Gaussian profile analysis."""
    # Input data
    prices: List[float] = field(default_factory=list)
    actual_volumes: List[float] = field(default_factory=list)

    # Fitted Gaussian parameters
    mu: float = 0.0          # Mean (center price)
    sigma: float = 0.0       # Standard deviation
    amplitude: float = 0.0   # Peak volume

    # Derived data
    gaussian_volumes: List[float] = field(default_factory=list)  # Ideal bell curve volumes
    volume_gaps: List[float] = field(default_factory=list)       # Gap to fill (positive = need more)
    gap_percentages: List[float] = field(default_factory=list)   # Gap as % of ideal

    # Statistics
    r_squared: float = 0.0         # Goodness of fit
    skewness: float = 0.0          # Distribution skewness
    kurtosis: float = 0.0          # Distribution kurtosis
    total_actual_volume: float = 0.0
    total_gaussian_volume: float = 0.0
    total_gap_volume: float = 0.0

    # Key levels
    poc_price: float = 0.0         # Point of Control (highest volume price)
    value_area_high: float = 0.0   # Value Area High (1 std above mean)
    value_area_low: float = 0.0    # Value Area Low (1 std below mean)


def gaussian_function(x: np.ndarray, amplitude: float, mu: float, sigma: float) -> np.ndarray:
    """Standard Gaussian function: A * exp(-0.5 * ((x - mu) / sigma)^2)"""
    return amplitude * np.exp(-0.5 * ((x - mu) / sigma) ** 2)


def fit_gaussian(prices: List[float], volumes: List[float]) -> Tuple[float, float, float]:
    """
    Fit a Gaussian curve to volume-at-price data.

    Returns:
        (amplitude, mu, sigma) - Fitted Gaussian parameters
    """
    prices_arr = np.array(prices, dtype=float)
    volumes_arr = np.array(volumes, dtype=float)

    # Initial parameter estimates
    total_vol = np.sum(volumes_arr)
    if total_vol == 0:
        mid = (prices_arr[0] + prices_arr[-1]) / 2
        return 1.0, mid, (prices_arr[-1] - prices_arr[0]) / 6

    # Weighted mean and std as initial guesses
    weights = volumes_arr / total_vol
    mu_init = np.sum(prices_arr * weights)
    sigma_init = np.sqrt(np.sum(weights * (prices_arr - mu_init) ** 2))
    amplitude_init = np.max(volumes_arr)

    if sigma_init == 0:
        sigma_init = (prices_arr[-1] - prices_arr[0]) / 6

    try:
        popt, _ = curve_fit(
            gaussian_function,
            prices_arr,
            volumes_arr,
            p0=[amplitude_init, mu_init, sigma_init],
            bounds=(
                [0, prices_arr.min() - (prices_arr.max() - prices_arr.min()),
                 sigma_init * 0.1],
                [amplitude_init * 3, prices_arr.max() + (prices_arr.max() - prices_arr.min()),
                 (prices_arr.max() - prices_arr.min())]
            ),
            maxfev=10000
        )
        return float(popt[0]), float(popt[1]), float(abs(popt[2]))
    except (RuntimeError, ValueError):
        # Fallback to moment-based estimates
        return float(amplitude_init), float(mu_init), float(sigma_init)


def analyze_gaussian_profile(prices: List[float],
                              volumes: List[float],
                              target_total_volume: Optional[float] = None) -> GaussianResult:
    """
    Perform full Gaussian profile analysis on volume-at-price data.

    Parameters:
        prices: List of price levels
        volumes: List of actual volumes at each price level
        target_total_volume: Optional target total volume for the Gaussian curve.
                           If None, uses the actual total volume.

    Returns:
        GaussianResult with complete analysis data
    """
    prices_arr = np.array(prices, dtype=float)
    volumes_arr = np.array(volumes, dtype=float)

    # Fit Gaussian curve
    amplitude, mu, sigma = fit_gaussian(prices, volumes)

    # Generate ideal Gaussian volumes
    gaussian_vols = gaussian_function(prices_arr, amplitude, mu, sigma)

    # Scale Gaussian to match total actual volume if no target specified
    actual_total = float(np.sum(volumes_arr))
    gaussian_total = float(np.sum(gaussian_vols))

    if target_total_volume is not None:
        scale_factor = target_total_volume / gaussian_total if gaussian_total > 0 else 1.0
    else:
        scale_factor = actual_total / gaussian_total if gaussian_total > 0 else 1.0

    gaussian_vols_scaled = gaussian_vols * scale_factor
    amplitude_scaled = amplitude * scale_factor

    # Calculate volume gaps (positive = volume to ADD to match Gaussian)
    volume_gaps = gaussian_vols_scaled - volumes_arr
    gap_percentages = np.where(
        gaussian_vols_scaled > 0,
        (volume_gaps / gaussian_vols_scaled) * 100,
        0.0
    )

    # Calculate R-squared (goodness of fit)
    ss_res = np.sum((volumes_arr - gaussian_vols_scaled) ** 2)
    ss_tot = np.sum((volumes_arr - np.mean(volumes_arr)) ** 2)
    r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0.0

    # Calculate distribution statistics
    if actual_total > 0:
        weights = volumes_arr / actual_total
        weighted_mean = np.sum(prices_arr * weights)
        weighted_var = np.sum(weights * (prices_arr - weighted_mean) ** 2)
        weighted_std = np.sqrt(weighted_var)

        if weighted_std > 0:
            skewness = float(np.sum(weights * ((prices_arr - weighted_mean) / weighted_std) ** 3))
            kurtosis = float(np.sum(weights * ((prices_arr - weighted_mean) / weighted_std) ** 4) - 3)
        else:
            skewness = 0.0
            kurtosis = 0.0
    else:
        skewness = 0.0
        kurtosis = 0.0

    # Key levels
    poc_idx = int(np.argmax(volumes_arr))
    poc_price = float(prices_arr[poc_idx])
    value_area_high = mu + sigma
    value_area_low = mu - sigma

    result = GaussianResult(
        prices=list(np.round(prices_arr, 2)),
        actual_volumes=list(np.round(volumes_arr, 2)),
        mu=round(mu, 2),
        sigma=round(sigma, 2),
        amplitude=round(amplitude_scaled, 2),
        gaussian_volumes=list(np.round(gaussian_vols_scaled, 2)),
        volume_gaps=list(np.round(volume_gaps, 2)),
        gap_percentages=list(np.round(gap_percentages, 2)),
        r_squared=round(r_squared, 4),
        skewness=round(skewness, 4),
        kurtosis=round(kurtosis, 4),
        total_actual_volume=round(actual_total, 2),
        total_gaussian_volume=round(float(np.sum(gaussian_vols_scaled)), 2),
        total_gap_volume=round(float(np.sum(np.maximum(volume_gaps, 0))), 2),
        poc_price=poc_price,
        value_area_high=round(value_area_high, 2),
        value_area_low=round(value_area_low, 2),
    )

    return result


def result_to_dataframe(result: GaussianResult) -> pd.DataFrame:
    """Convert GaussianResult to a pandas DataFrame for display."""
    df = pd.DataFrame({
        'Price': result.prices,
        'Actual Volume': result.actual_volumes,
        'Gaussian Volume (Ideal)': result.gaussian_volumes,
        'Volume Gap (to Add)': result.volume_gaps,
        'Gap %': result.gap_percentages,
    })

    # Add zone classification
    df['Zone'] = df['Price'].apply(
        lambda p: 'Value Area' if result.value_area_low <= p <= result.value_area_high
        else ('Above VA' if p > result.value_area_high else 'Below VA')
    )

    # Add action recommendation
    df['Action'] = df['Volume Gap (to Add)'].apply(
        lambda g: 'ADD volume' if g > 0 else ('EXCESS volume' if g < 0 else 'MATCHED')
    )

    return df


def get_summary_stats(result: GaussianResult) -> dict:
    """Get a summary dictionary of the Gaussian analysis."""
    return {
        'Point of Control (POC)': result.poc_price,
        'Gaussian Mean (Center)': result.mu,
        'Gaussian Std Dev': result.sigma,
        'Value Area High': result.value_area_high,
        'Value Area Low': result.value_area_low,
        'R-squared (Fit Quality)': result.r_squared,
        'Skewness': result.skewness,
        'Kurtosis': result.kurtosis,
        'Total Actual Volume': result.total_actual_volume,
        'Total Volume to Add': result.total_gap_volume,
    }
