"""
dashboard.py - Streamlit Dashboard for Gaussian Volume Profile Analysis.

Features:
- Upload/paste stock chart images (Volume on LHS, Price on RHS)
- Extract volume-at-price data from chart images
- Fit Gaussian bell curve and show volume gaps
- Display analysis in table format
- Maintain history per symbol
- Dashboard overview of all analyzed symbols
"""

import streamlit as st
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
from datetime import datetime
import io

from gaussian_chart_analyzer.chart_extractor import (
    read_chart_from_bytes,
    extract_chart_data,
    create_sample_data,
)
from gaussian_chart_analyzer.gaussian_profile import (
    analyze_gaussian_profile,
    result_to_dataframe,
    get_summary_stats,
    gaussian_function,
    GaussianResult,
)
from gaussian_chart_analyzer.data_store import (
    save_analysis,
    get_symbols,
    get_symbol_history,
    get_all_latest_analyses,
    delete_analysis,
    delete_symbol,
)

# --- Page Configuration ---
st.set_page_config(
    page_title="RamGaus - Gaussian Volume Profile Analyzer",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Custom CSS ---
st.markdown("""
<style>
    .main-header {
        font-size: 2rem;
        font-weight: 700;
        color: #1f77b4;
        margin-bottom: 0.5rem;
    }
    .sub-header {
        font-size: 1rem;
        color: #666;
        margin-bottom: 1.5rem;
    }
    .metric-card {
        background: #f0f2f6;
        border-radius: 10px;
        padding: 1rem;
        text-align: center;
    }
    .gap-positive { color: #d32f2f; font-weight: bold; }
    .gap-negative { color: #388e3c; font-weight: bold; }
    .stDataFrame { font-size: 0.85rem; }
</style>
""", unsafe_allow_html=True)


def plot_gaussian_analysis(result: GaussianResult, symbol: str = "") -> plt.Figure:
    """
    Create a comprehensive visualization of the Gaussian profile analysis.
    Shows actual volume vs. ideal Gaussian curve with gap highlighting.
    """
    fig, axes = plt.subplots(1, 3, figsize=(18, 8))

    prices = np.array(result.prices)
    actual = np.array(result.actual_volumes)
    gaussian = np.array(result.gaussian_volumes)
    gaps = np.array(result.volume_gaps)

    title_prefix = f"{symbol} - " if symbol else ""

    # --- Plot 1: Volume Profile with Gaussian Overlay ---
    ax1 = axes[0]
    bar_width = (prices[-1] - prices[0]) / len(prices) * 0.8 if len(prices) > 1 else 1.0

    # Color bars: green where actual >= gaussian, red where actual < gaussian
    colors = ['#4CAF50' if a >= g else '#F44336' for a, g in zip(actual, gaussian)]
    ax1.barh(prices, actual, height=bar_width, color=colors, alpha=0.7, label='Actual Volume')
    ax1.plot(gaussian, prices, 'b-', linewidth=2.5, label='Gaussian Profile')
    ax1.axhline(y=result.mu, color='orange', linestyle='--', alpha=0.8, label=f'Mean: {result.mu}')
    ax1.axhline(y=result.value_area_high, color='purple', linestyle=':', alpha=0.6,
                label=f'VA High: {result.value_area_high}')
    ax1.axhline(y=result.value_area_low, color='purple', linestyle=':', alpha=0.6,
                label=f'VA Low: {result.value_area_low}')
    ax1.set_xlabel('Volume', fontsize=11)
    ax1.set_ylabel('Price', fontsize=11)
    ax1.set_title(f'{title_prefix}Volume Profile vs Gaussian', fontsize=13, fontweight='bold')
    ax1.legend(fontsize=8, loc='upper right')
    ax1.grid(True, alpha=0.3)
    ax1.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{x:,.0f}'))

    # --- Plot 2: Volume Gap Analysis ---
    ax2 = axes[1]
    gap_colors = ['#d32f2f' if g > 0 else '#388e3c' for g in gaps]
    ax2.barh(prices, gaps, height=bar_width, color=gap_colors, alpha=0.7)
    ax2.axvline(x=0, color='black', linewidth=1)
    ax2.axhline(y=result.poc_price, color='gold', linestyle='--', linewidth=1.5,
                label=f'POC: {result.poc_price}')
    ax2.set_xlabel('Volume Gap (+ = need to add)', fontsize=11)
    ax2.set_ylabel('Price', fontsize=11)
    ax2.set_title(f'{title_prefix}Volume Gaps to Complete Bell Curve', fontsize=13, fontweight='bold')
    ax2.legend(fontsize=9)
    ax2.grid(True, alpha=0.3)
    ax2.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{x:,.0f}'))

    # --- Plot 3: Overlay Comparison ---
    ax3 = axes[2]
    ax3.fill_betweenx(prices, 0, actual, alpha=0.3, color='blue', label='Actual')
    ax3.fill_betweenx(prices, 0, gaussian, alpha=0.3, color='red', label='Gaussian Ideal')
    ax3.plot(actual, prices, 'b-', linewidth=1.5)
    ax3.plot(gaussian, prices, 'r--', linewidth=1.5)
    ax3.set_xlabel('Volume', fontsize=11)
    ax3.set_ylabel('Price', fontsize=11)
    ax3.set_title(f'{title_prefix}Actual vs Gaussian Overlay', fontsize=13, fontweight='bold')
    ax3.legend(fontsize=9)
    ax3.grid(True, alpha=0.3)
    ax3.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{x:,.0f}'))

    plt.tight_layout()
    return fig


def plot_bell_curve_only(result: GaussianResult, symbol: str = "") -> plt.Figure:
    """Plot the ideal Gaussian bell curve for the data."""
    fig, ax = plt.subplots(figsize=(8, 5))

    prices = np.array(result.prices)
    smooth_prices = np.linspace(prices.min(), prices.max(), 200)
    smooth_gaussian = gaussian_function(smooth_prices, result.amplitude, result.mu, result.sigma)

    ax.fill_between(smooth_prices, smooth_gaussian, alpha=0.3, color='blue')
    ax.plot(smooth_prices, smooth_gaussian, 'b-', linewidth=2, label='Gaussian Bell Curve')
    ax.scatter(prices, result.actual_volumes, color='red', s=30, zorder=5, label='Actual Data Points')

    ax.axvline(x=result.mu, color='orange', linestyle='--', label=f'Mean: {result.mu}')
    ax.axvline(x=result.mu - result.sigma, color='green', linestyle=':', label=f'-1σ: {result.mu - result.sigma:.2f}')
    ax.axvline(x=result.mu + result.sigma, color='green', linestyle=':', label=f'+1σ: {result.mu + result.sigma:.2f}')

    title_prefix = f"{symbol} - " if symbol else ""
    ax.set_title(f'{title_prefix}Gaussian Bell Curve Distribution', fontsize=14, fontweight='bold')
    ax.set_xlabel('Price', fontsize=12)
    ax.set_ylabel('Volume', fontsize=12)
    ax.legend(fontsize=9)
    ax.grid(True, alpha=0.3)
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f'{x:,.0f}'))

    plt.tight_layout()
    return fig


# =====================================================================
# SIDEBAR
# =====================================================================
with st.sidebar:
    st.markdown("## RamGaus Analyzer")
    st.markdown("*Gaussian Volume Profile Analysis*")
    st.markdown("---")

    page = st.radio(
        "Navigate",
        ["📊 Analyze Chart", "📋 Dashboard", "📜 Symbol History"],
        index=0
    )

    st.markdown("---")
    st.markdown("### Saved Symbols")
    symbols = get_symbols()
    if symbols:
        for sym in symbols:
            st.markdown(f"- **{sym}**")
    else:
        st.markdown("*No analyses saved yet*")


# =====================================================================
# PAGE: ANALYZE CHART
# =====================================================================
if page == "📊 Analyze Chart":
    st.markdown('<div class="main-header">📊 Chart Analysis - Gaussian Volume Profile</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Upload a stock chart image (Volume on LHS, Price on RHS) '
                'or use manual data entry. The tool extracts volume-at-price data and fits a '
                'Gaussian bell curve distribution.</div>', unsafe_allow_html=True)

    # --- Input Method Selection ---
    input_method = st.radio(
        "Choose input method:",
        ["Upload Chart Image", "Manual Data Entry", "Demo with Sample Data"],
        horizontal=True,
    )

    symbol_name = st.text_input("Symbol Name (e.g., NIFTY, RELIANCE, BANKNIFTY):", value="", key="symbol_input")

    result = None

    if input_method == "Upload Chart Image":
        st.markdown("### Upload Chart Image")
        st.info("Upload a chart with Volume Profile on the left Y-axis and Price on the right Y-axis. "
                "Supported formats: PNG, JPG, JPEG, BMP")

        uploaded_file = st.file_uploader("Choose a chart image", type=["png", "jpg", "jpeg", "bmp"])

        col_params1, col_params2, col_params3 = st.columns(3)
        with col_params1:
            price_min = st.number_input("Price Min (RHS bottom)", value=0.0, step=1.0,
                                        help="Minimum price on the right Y-axis. Set to 0 for auto-detect.")
        with col_params2:
            price_max = st.number_input("Price Max (RHS top)", value=0.0, step=1.0,
                                        help="Maximum price on the right Y-axis. Set to 0 for auto-detect.")
        with col_params3:
            volume_max = st.number_input("Volume Max (LHS)", value=0.0, step=1000.0,
                                         help="Maximum volume on the left Y-axis. Set to 0 for auto-detect.")

        num_levels = st.slider("Number of price levels to analyze:", min_value=10, max_value=100, value=30)

        if uploaded_file is not None:
            # Display the uploaded image
            st.image(uploaded_file, caption="Uploaded Chart", use_container_width=True)

            if st.button("🔍 Extract & Analyze", type="primary"):
                with st.spinner("Processing chart image..."):
                    # Read image
                    image_bytes = uploaded_file.getvalue()
                    img = read_chart_from_bytes(image_bytes)

                    # Extract data
                    p_min = price_min if price_min > 0 else None
                    p_max = price_max if price_max > 0 else None
                    v_max = volume_max if volume_max > 0 else None

                    chart_data = extract_chart_data(
                        img,
                        price_min=p_min,
                        price_max=p_max,
                        volume_max=v_max,
                        num_levels=num_levels,
                    )

                    if chart_data.prices and chart_data.volumes:
                        result = analyze_gaussian_profile(chart_data.prices, chart_data.volumes)
                        st.success(f"Extracted {len(chart_data.prices)} price levels from chart.")
                    else:
                        st.error("Could not extract data from the chart image. "
                                 "Please provide Price Min/Max and Volume Max manually.")

    elif input_method == "Manual Data Entry":
        st.markdown("### Manual Data Entry")
        st.info("Enter price and volume data directly. One pair per row.")

        col_left, col_right = st.columns(2)
        with col_left:
            prices_text = st.text_area(
                "Prices (one per line):",
                placeholder="100\n105\n110\n115\n120\n125\n130",
                height=250,
            )
        with col_right:
            volumes_text = st.text_area(
                "Volumes (one per line):",
                placeholder="5000\n12000\n35000\n80000\n45000\n15000\n3000",
                height=250,
            )

        if st.button("🔍 Analyze Data", type="primary"):
            try:
                prices = [float(p.strip()) for p in prices_text.strip().split('\n') if p.strip()]
                volumes = [float(v.strip().replace(',', '')) for v in volumes_text.strip().split('\n') if v.strip()]

                if len(prices) != len(volumes):
                    st.error(f"Price count ({len(prices)}) must match volume count ({len(volumes)}).")
                elif len(prices) < 3:
                    st.error("Need at least 3 data points for Gaussian analysis.")
                else:
                    result = analyze_gaussian_profile(prices, volumes)
                    st.success(f"Analyzed {len(prices)} price levels.")
            except ValueError as e:
                st.error(f"Invalid input: {e}. Please enter numeric values only.")

    elif input_method == "Demo with Sample Data":
        st.markdown("### Demo Mode")

        col_d1, col_d2 = st.columns(2)
        with col_d1:
            demo_price_min = st.number_input("Demo Price Min", value=100.0, step=10.0)
        with col_d2:
            demo_price_max = st.number_input("Demo Price Max", value=200.0, step=10.0)

        demo_levels = st.slider("Number of price levels:", min_value=10, max_value=60, value=30, key="demo_levels")

        if st.button("🎲 Generate & Analyze Sample", type="primary"):
            sample_data = create_sample_data(
                symbol=symbol_name or "DEMO",
                price_min=demo_price_min,
                price_max=demo_price_max,
                num_levels=demo_levels,
            )
            result = analyze_gaussian_profile(sample_data.prices, sample_data.volumes)
            st.success("Sample data generated and analyzed.")

    # --- Display Results ---
    if result is not None:
        st.markdown("---")
        st.markdown("## Analysis Results")

        # --- Summary Metrics ---
        stats = get_summary_stats(result)
        col1, col2, col3, col4, col5 = st.columns(5)
        with col1:
            st.metric("POC Price", f"{stats['Point of Control (POC)']:.2f}")
        with col2:
            st.metric("Gaussian Mean", f"{stats['Gaussian Mean (Center)']:.2f}")
        with col3:
            st.metric("Std Dev (σ)", f"{stats['Gaussian Std Dev']:.2f}")
        with col4:
            st.metric("R² (Fit)", f"{stats['R-squared (Fit Quality)']:.4f}")
        with col5:
            st.metric("Volume to Add", f"{stats['Total Volume to Add']:,.0f}")

        col6, col7, col8, col9 = st.columns(4)
        with col6:
            st.metric("Value Area High", f"{stats['Value Area High']:.2f}")
        with col7:
            st.metric("Value Area Low", f"{stats['Value Area Low']:.2f}")
        with col8:
            st.metric("Skewness", f"{stats['Skewness']:.4f}")
        with col9:
            st.metric("Kurtosis", f"{stats['Kurtosis']:.4f}")

        # --- Charts ---
        st.markdown("### Gaussian Profile Visualization")
        fig = plot_gaussian_analysis(result, symbol=symbol_name)
        st.pyplot(fig)
        plt.close(fig)

        st.markdown("### Bell Curve Distribution")
        fig2 = plot_bell_curve_only(result, symbol=symbol_name)
        st.pyplot(fig2)
        plt.close(fig2)

        # --- Data Table ---
        st.markdown("### Volume-at-Price Table (Gaussian Gap Analysis)")
        st.markdown("**Red gaps** = volume needs to be ADDED at that price. "
                     "**Green** = excess volume already present.")

        df = result_to_dataframe(result)

        # Style the dataframe
        def highlight_gaps(val):
            if isinstance(val, (int, float)):
                if val > 0:
                    return 'color: #d32f2f; font-weight: bold'
                elif val < 0:
                    return 'color: #388e3c; font-weight: bold'
            return ''

        styled_df = df.style.applymap(highlight_gaps, subset=['Volume Gap (to Add)', 'Gap %'])
        st.dataframe(styled_df, use_container_width=True, height=500)

        # --- Download button ---
        csv_buffer = io.StringIO()
        df.to_csv(csv_buffer, index=False)
        st.download_button(
            label="📥 Download Table as CSV",
            data=csv_buffer.getvalue(),
            file_name=f"{symbol_name or 'analysis'}_gaussian_profile_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv",
            mime="text/csv",
        )

        # --- Save to History ---
        st.markdown("---")
        st.markdown("### Save to Dashboard")
        notes = st.text_input("Analysis notes (optional):", key="save_notes")

        if st.button("💾 Save Analysis to Dashboard", type="primary"):
            if not symbol_name:
                st.warning("Please enter a Symbol Name above before saving.")
            else:
                analysis_id = save_analysis(symbol_name, result, notes=notes)
                st.success(f"Analysis saved for **{symbol_name.upper()}** (ID: {analysis_id})")
                st.balloons()


# =====================================================================
# PAGE: DASHBOARD
# =====================================================================
elif page == "📋 Dashboard":
    st.markdown('<div class="main-header">📋 Symbol Dashboard</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">Overview of all analyzed symbols with their latest Gaussian profile data.</div>',
                unsafe_allow_html=True)

    latest_analyses = get_all_latest_analyses()

    if not latest_analyses:
        st.info("No analyses saved yet. Go to '📊 Analyze Chart' to get started.")
    else:
        # --- Summary Table ---
        st.markdown("### All Symbols - Latest Analysis")
        overview_data = []
        for entry in latest_analyses:
            overview_data.append({
                'Symbol': entry['symbol'],
                'Last Analyzed': entry['timestamp'][:19].replace('T', ' '),
                'POC Price': entry['poc_price'],
                'Mean (μ)': entry['mu'],
                'Std Dev (σ)': entry['sigma'],
                'R²': entry['r_squared'],
                'Skewness': entry['skewness'],
                'VA High': entry['value_area_high'],
                'VA Low': entry['value_area_low'],
                'Gap Volume': f"{entry['total_gap_volume']:,.0f}",
                '# Analyses': entry['total_analyses'],
            })

        overview_df = pd.DataFrame(overview_data)
        st.dataframe(overview_df, use_container_width=True, hide_index=True)

        # --- Per-Symbol Detail Cards ---
        st.markdown("---")
        st.markdown("### Symbol Detail Cards")

        cols_per_row = 2
        for i in range(0, len(latest_analyses), cols_per_row):
            cols = st.columns(cols_per_row)
            for j, col in enumerate(cols):
                idx = i + j
                if idx >= len(latest_analyses):
                    break

                entry = latest_analyses[idx]
                with col:
                    st.markdown(f"#### {entry['symbol']}")

                    # Reconstruct a GaussianResult for plotting
                    mini_result = GaussianResult(
                        prices=entry['prices'],
                        actual_volumes=entry['actual_volumes'],
                        gaussian_volumes=entry['gaussian_volumes'],
                        volume_gaps=entry['volume_gaps'],
                        gap_percentages=entry['gap_percentages'],
                        mu=entry['mu'],
                        sigma=entry['sigma'],
                        amplitude=entry.get('amplitude', 0),
                        r_squared=entry['r_squared'],
                        poc_price=entry['poc_price'],
                        value_area_high=entry['value_area_high'],
                        value_area_low=entry['value_area_low'],
                        total_actual_volume=entry['total_actual_volume'],
                        total_gap_volume=entry['total_gap_volume'],
                    )

                    # Mini bell curve plot
                    fig = plot_bell_curve_only(mini_result, symbol=entry['symbol'])
                    st.pyplot(fig)
                    plt.close(fig)

                    # Quick stats
                    m1, m2, m3 = st.columns(3)
                    with m1:
                        st.metric("POC", f"{entry['poc_price']:.2f}")
                    with m2:
                        st.metric("R²", f"{entry['r_squared']:.3f}")
                    with m3:
                        st.metric("Gap Vol", f"{entry['total_gap_volume']:,.0f}")

                    if entry.get('notes'):
                        st.caption(f"Notes: {entry['notes']}")


# =====================================================================
# PAGE: SYMBOL HISTORY
# =====================================================================
elif page == "📜 Symbol History":
    st.markdown('<div class="main-header">📜 Symbol Analysis History</div>', unsafe_allow_html=True)
    st.markdown('<div class="sub-header">View and compare past analyses for each symbol.</div>',
                unsafe_allow_html=True)

    symbols = get_symbols()

    if not symbols:
        st.info("No analyses saved yet. Go to '📊 Analyze Chart' to get started.")
    else:
        selected_symbol = st.selectbox("Select Symbol:", symbols)

        if selected_symbol:
            history = get_symbol_history(selected_symbol)

            st.markdown(f"### {selected_symbol} - {len(history)} Analysis Record(s)")

            # History overview table
            hist_data = []
            for entry in history:
                hist_data.append({
                    'ID': entry['id'],
                    'Date/Time': entry['timestamp'][:19].replace('T', ' '),
                    'POC': entry['poc_price'],
                    'Mean': entry['mu'],
                    'Sigma': entry['sigma'],
                    'R²': entry['r_squared'],
                    'Skew': entry['skewness'],
                    'Gap Volume': f"{entry['total_gap_volume']:,.0f}",
                    'Notes': entry.get('notes', ''),
                })

            hist_df = pd.DataFrame(hist_data)
            st.dataframe(hist_df, use_container_width=True, hide_index=True)

            # Detailed view of selected analysis
            st.markdown("---")
            analysis_ids = [f"{h['id']} ({h['timestamp'][:19]})" for h in history]
            selected_analysis = st.selectbox("Select analysis to view details:", analysis_ids)

            if selected_analysis:
                selected_id = selected_analysis.split(" (")[0]
                entry = None
                for h in history:
                    if h['id'] == selected_id:
                        entry = h
                        break

                if entry:
                    # Reconstruct GaussianResult
                    detail_result = GaussianResult(
                        prices=entry['prices'],
                        actual_volumes=entry['actual_volumes'],
                        gaussian_volumes=entry['gaussian_volumes'],
                        volume_gaps=entry['volume_gaps'],
                        gap_percentages=entry['gap_percentages'],
                        mu=entry['mu'],
                        sigma=entry['sigma'],
                        amplitude=entry.get('amplitude', 0),
                        r_squared=entry['r_squared'],
                        skewness=entry['skewness'],
                        kurtosis=entry.get('kurtosis', 0),
                        poc_price=entry['poc_price'],
                        value_area_high=entry['value_area_high'],
                        value_area_low=entry['value_area_low'],
                        total_actual_volume=entry['total_actual_volume'],
                        total_gap_volume=entry['total_gap_volume'],
                    )

                    # Full analysis charts
                    fig = plot_gaussian_analysis(detail_result, symbol=selected_symbol)
                    st.pyplot(fig)
                    plt.close(fig)

                    # Data table
                    df = result_to_dataframe(detail_result)
                    st.dataframe(df, use_container_width=True, height=400)

                    # Download
                    csv_buf = io.StringIO()
                    df.to_csv(csv_buf, index=False)
                    st.download_button(
                        label="📥 Download as CSV",
                        data=csv_buf.getvalue(),
                        file_name=f"{selected_symbol}_{selected_id}_gaussian.csv",
                        mime="text/csv",
                    )

            # --- Delete options ---
            st.markdown("---")
            st.markdown("### Manage History")
            col_del1, col_del2 = st.columns(2)
            with col_del1:
                del_id = st.text_input("Analysis ID to delete:")
                if st.button("🗑 Delete Analysis"):
                    if del_id:
                        if delete_analysis(selected_symbol, del_id):
                            st.success(f"Deleted analysis {del_id}")
                            st.rerun()
                        else:
                            st.error("Analysis not found.")
            with col_del2:
                st.markdown("")
                st.markdown("")
                if st.button(f"🗑 Delete ALL history for {selected_symbol}", type="secondary"):
                    if delete_symbol(selected_symbol):
                        st.success(f"All history for {selected_symbol} deleted.")
                        st.rerun()
