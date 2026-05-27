# Notes

## Purpose

Overlay indicator that combines higher-timeframe candle overlays, structural zones, moving averages, Bollinger Bands, session highlighting, and a futures value panel.

## Current Behavior

Draws 1H, 4H, and daily candle overlays with optional labels, structural stack and gap zones, an HTF distance table, optional moving averages, Bollinger Bands, session shading, and a futures value reference table. Breakout zones can display as exact-anchor boxes, floating-window boxes, or fill-between-candles areas that follow the same plot/fill style used by Session High/Low Fill.

## Inputs

Includes inputs for HTF overlays, overlay labels, daily and higher-timeframe zone visibility and styling, breakout zone display mode, Points Till Break labels, zone alerts, HTF distance table settings, moving averages, Bollinger Bands, session highlighting, and futures value panel display.

## Visuals

Uses boxes, lines, labels, plots, fills, background shading, and tables on an `overlay=true` chart.

## Alerts

Contains `alertcondition()` entries and optional dynamic `alert()` messages for stack zones, HTF stack zones, H1 sweep gaps, and MA 1 / MA 2 crosses.

## Known Issues

Unknown from initial import.

## Future Ideas

Unknown from initial import.
