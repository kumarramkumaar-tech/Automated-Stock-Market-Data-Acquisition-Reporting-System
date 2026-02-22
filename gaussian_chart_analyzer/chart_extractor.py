"""
chart_extractor.py - Extract Volume-at-Price data from stock chart images.

Reads chart images where:
  - Left Y-axis (LHS) = Volume
  - Right Y-axis (RHS) = Price

Uses OpenCV for image processing and pytesseract for OCR to read axis labels.
Detects horizontal volume bars and maps them to price levels.
"""

import cv2
import numpy as np
import re
from dataclasses import dataclass, field
from typing import List, Tuple, Optional


@dataclass
class ChartData:
    """Extracted data from a stock chart image."""
    prices: List[float] = field(default_factory=list)
    volumes: List[float] = field(default_factory=list)
    price_min: float = 0.0
    price_max: float = 0.0
    volume_max: float = 0.0
    image_height: int = 0
    image_width: int = 0


def read_chart_image(image_path: str) -> np.ndarray:
    """Read and validate a chart image file."""
    img = cv2.imread(image_path)
    if img is None:
        raise ValueError(f"Could not read image: {image_path}")
    return img


def read_chart_from_bytes(image_bytes: bytes) -> np.ndarray:
    """Read chart image from raw bytes (for upload handling)."""
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("Could not decode image from bytes")
    return img


def _detect_chart_region(img: np.ndarray) -> Tuple[int, int, int, int]:
    """
    Detect the main chart plotting area (excluding axes labels).
    Returns (x_start, y_start, x_end, y_end) of the chart region.
    """
    h, w = img.shape[:2]
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # Detect edges to find chart boundaries
    edges = cv2.Canny(gray, 50, 150)

    # Find the chart frame by looking for long horizontal and vertical lines
    lines = cv2.HoughLinesP(edges, 1, np.pi / 180, threshold=100,
                            minLineLength=min(w, h) // 4, maxLineGap=10)

    if lines is not None and len(lines) > 0:
        # Find bounding box of the main chart area
        x_coords = []
        y_coords = []
        for line in lines:
            x1, y1, x2, y2 = line[0]
            x_coords.extend([x1, x2])
            y_coords.extend([y1, y2])

        x_start = max(int(np.percentile(x_coords, 10)), int(w * 0.08))
        x_end = min(int(np.percentile(x_coords, 90)), int(w * 0.92))
        y_start = max(int(np.percentile(y_coords, 5)), int(h * 0.05))
        y_end = min(int(np.percentile(y_coords, 95)), int(h * 0.90))
    else:
        # Default: assume chart occupies central ~80% of image
        x_start = int(w * 0.10)
        x_end = int(w * 0.88)
        y_start = int(h * 0.05)
        y_end = int(h * 0.85)

    return x_start, y_start, x_end, y_end


def _extract_axis_numbers_ocr(img: np.ndarray, region: str = "right") -> List[float]:
    """
    Try to extract numeric labels from axis regions using pytesseract OCR.
    Falls back gracefully if pytesseract is not available.
    """
    try:
        import pytesseract
    except ImportError:
        return []

    h, w = img.shape[:2]

    if region == "right":
        # Right axis region (Price)
        axis_img = img[:, int(w * 0.88):, :]
    elif region == "left":
        # Left axis region (Volume)
        axis_img = img[:, :int(w * 0.12), :]
    else:
        return []

    # Preprocess for OCR
    gray = cv2.cvtColor(axis_img, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)

    try:
        text = pytesseract.image_to_string(thresh, config='--psm 6 -c tessedit_char_whitelist=0123456789.,')
        numbers = []
        for line in text.strip().split('\n'):
            line = line.strip().replace(',', '')
            match = re.search(r'[\d]+\.?[\d]*', line)
            if match:
                numbers.append(float(match.group()))
        return sorted(numbers)
    except Exception:
        return []


def _detect_volume_bars(img: np.ndarray, chart_region: Tuple[int, int, int, int],
                        num_price_levels: int = 30) -> List[Tuple[int, float]]:
    """
    Detect horizontal volume bars in the chart image.
    Returns list of (y_position, relative_bar_length) tuples.

    Volume bars in a Volume Profile chart are horizontal bars originating
    from the left side, with length proportional to volume at that price level.
    """
    x_start, y_start, x_end, y_end = chart_region
    chart_crop = img[y_start:y_end, x_start:x_end]
    h, w = chart_crop.shape[:2]

    # Convert to HSV to detect colored bars
    hsv = cv2.cvtColor(chart_crop, cv2.COLOR_BGR2HSV)

    # Detect common volume bar colors:
    # Blue bars (common in volume profiles)
    blue_lower = np.array([100, 50, 50])
    blue_upper = np.array([130, 255, 255])
    blue_mask = cv2.inRange(hsv, blue_lower, blue_upper)

    # Red bars (sell volume)
    red_lower1 = np.array([0, 50, 50])
    red_upper1 = np.array([10, 255, 255])
    red_lower2 = np.array([170, 50, 50])
    red_upper2 = np.array([180, 255, 255])
    red_mask = cv2.inRange(hsv, red_lower1, red_upper1) | cv2.inRange(hsv, red_lower2, red_upper2)

    # Green bars (buy volume)
    green_lower = np.array([35, 50, 50])
    green_upper = np.array([85, 255, 255])
    green_mask = cv2.inRange(hsv, green_lower, green_upper)

    # Yellow/Orange bars
    yellow_lower = np.array([15, 50, 50])
    yellow_upper = np.array([35, 255, 255])
    yellow_mask = cv2.inRange(hsv, yellow_lower, yellow_upper)

    # Combine all color masks
    combined_mask = blue_mask | red_mask | green_mask | yellow_mask

    # Also detect dark bars (gray/black bars on white background)
    gray = cv2.cvtColor(chart_crop, cv2.COLOR_BGR2GRAY)
    _, dark_mask = cv2.threshold(gray, 100, 255, cv2.THRESH_BINARY_INV)
    combined_mask = combined_mask | dark_mask

    # Divide the chart height into price-level rows
    row_height = max(h // num_price_levels, 1)
    bars = []

    for i in range(num_price_levels):
        y_row_start = i * row_height
        y_row_end = min((i + 1) * row_height, h)
        row_slice = combined_mask[y_row_start:y_row_end, :]

        # Measure bar length as the rightmost non-zero pixel from the left
        col_sums = np.sum(row_slice > 0, axis=0)
        if np.any(col_sums > row_height * 0.2):
            # Find the extent of the bar
            nonzero_cols = np.where(col_sums > row_height * 0.2)[0]
            if len(nonzero_cols) > 0:
                bar_length = float(nonzero_cols[-1]) / w
                y_center = y_start + (y_row_start + y_row_end) // 2
                bars.append((y_center, bar_length))

    return bars


def _detect_candlesticks_and_line(img: np.ndarray,
                                   chart_region: Tuple[int, int, int, int]) -> List[Tuple[int, float]]:
    """
    Detect price data from candlestick or line chart elements.
    Returns list of (x_position, relative_y_position) for price line.
    """
    x_start, y_start, x_end, y_end = chart_region
    chart_crop = img[y_start:y_end, x_start:x_end]
    h, w = chart_crop.shape[:2]

    # Convert to grayscale and detect prominent lines
    gray = cv2.cvtColor(chart_crop, cv2.COLOR_BGR2GRAY)
    edges = cv2.Canny(gray, 30, 100)

    # Sample y-positions across x to build a price line
    price_points = []
    for x in range(0, w, max(w // 50, 1)):
        col = edges[:, x]
        nonzero = np.where(col > 0)[0]
        if len(nonzero) > 0:
            # Take the median y position of edge pixels in this column
            y_median = int(np.median(nonzero))
            relative_y = 1.0 - (y_median / h)  # Invert: top=high price
            price_points.append((x_start + x, relative_y))

    return price_points


def extract_chart_data(img: np.ndarray,
                       price_min: Optional[float] = None,
                       price_max: Optional[float] = None,
                       volume_max: Optional[float] = None,
                       num_levels: int = 30) -> ChartData:
    """
    Main extraction function: process a chart image and extract
    volume-at-price data.

    Parameters:
        img: OpenCV image (BGR)
        price_min: Minimum price on the RHS axis (auto-detected or manual)
        price_max: Maximum price on the RHS axis (auto-detected or manual)
        volume_max: Maximum volume on the LHS axis (auto-detected or manual)
        num_levels: Number of price levels to divide the chart into

    Returns:
        ChartData with extracted prices and volumes
    """
    h, w = img.shape[:2]

    # Step 1: Detect chart region
    chart_region = _detect_chart_region(img)

    # Step 2: Try OCR for axis labels
    if price_min is None or price_max is None:
        right_numbers = _extract_axis_numbers_ocr(img, "right")
        if len(right_numbers) >= 2:
            if price_min is None:
                price_min = right_numbers[0]
            if price_max is None:
                price_max = right_numbers[-1]

    if volume_max is None:
        left_numbers = _extract_axis_numbers_ocr(img, "left")
        if left_numbers:
            volume_max = max(left_numbers)

    # Default axis values if OCR fails
    if price_min is None:
        price_min = 100.0
    if price_max is None:
        price_max = 200.0
    if volume_max is None:
        volume_max = 1000000.0

    # Step 3: Detect volume bars
    volume_bars = _detect_volume_bars(img, chart_region, num_levels)

    # Step 4: Map pixel positions to price/volume values
    _, y_start, _, y_end = chart_region
    chart_height = y_end - y_start

    data = ChartData(
        price_min=price_min,
        price_max=price_max,
        volume_max=volume_max,
        image_height=h,
        image_width=w
    )

    if volume_bars:
        for y_pos, bar_length in volume_bars:
            # Map y position to price (top = high price, bottom = low price)
            relative_y = 1.0 - ((y_pos - y_start) / chart_height)
            relative_y = max(0.0, min(1.0, relative_y))
            price = price_min + relative_y * (price_max - price_min)

            # Map bar length to volume
            volume = bar_length * volume_max

            data.prices.append(round(price, 2))
            data.volumes.append(round(volume, 2))
    else:
        # Fallback: generate evenly spaced price levels with estimated volumes
        # based on pixel intensity analysis
        gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        x_start = chart_region[0]
        x_end = chart_region[2]

        for i in range(num_levels):
            relative_y = i / (num_levels - 1)
            price = price_max - relative_y * (price_max - price_min)

            # Estimate volume from pixel density in the left portion of chart
            y_pixel = y_start + int(relative_y * chart_height)
            row_start = max(0, y_pixel - chart_height // (2 * num_levels))
            row_end = min(h, y_pixel + chart_height // (2 * num_levels))
            left_region = gray[row_start:row_end, x_start:x_start + (x_end - x_start) // 3]

            if left_region.size > 0:
                # Darker pixels = more volume bars
                dark_ratio = np.mean(left_region < 128)
                volume = dark_ratio * volume_max
            else:
                volume = 0

            data.prices.append(round(price, 2))
            data.volumes.append(round(volume, 2))

    return data


def create_sample_data(symbol: str = "SAMPLE",
                       price_min: float = 100.0,
                       price_max: float = 200.0,
                       num_levels: int = 30) -> ChartData:
    """
    Create sample volume-at-price data for testing/demonstration.
    Generates a slightly skewed distribution to show the Gaussian gap analysis.
    """
    prices = np.linspace(price_min, price_max, num_levels)
    mid = (price_min + price_max) / 2
    std = (price_max - price_min) / 6

    # Create a realistic but imperfect volume profile
    rng = np.random.default_rng(42)
    base_volumes = np.exp(-0.5 * ((prices - mid) / std) ** 2) * 100000
    noise = rng.normal(1.0, 0.3, num_levels)
    noise = np.maximum(noise, 0.1)
    volumes = base_volumes * noise

    # Add some asymmetry (more volume above the midpoint)
    skew = 1 + 0.3 * (prices - mid) / (price_max - mid)
    volumes = volumes * np.maximum(skew, 0.2)

    data = ChartData(
        prices=list(np.round(prices, 2)),
        volumes=list(np.round(volumes, 2)),
        price_min=price_min,
        price_max=price_max,
        volume_max=float(np.max(volumes)),
        image_height=600,
        image_width=800
    )
    return data
