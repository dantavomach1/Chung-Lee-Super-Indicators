# Notes

## Purpose

Overlay indicator that calculates and displays three adaptive MACD sets with histogram, signal, background, and Fibonacci reference visuals.

## Current Behavior

Calculates three MACD values, their EMA signal lines, and histograms from the chart close. Optional background coloring is controlled by combined histogram and signal-line conditions.

## Inputs

Includes separate period, fast length, slow length, and signal length inputs for three MACD sets, plus toggles for plotting MACD lines, signal lines, and background color overlay.

## Visuals

Uses `overlay=true`, plots MACD lines, signal lines, area histograms with outlines, a zero line, positive and negative Fibonacci level lines, and optional green/red background shading.

## Alerts

No `alertcondition()` or `alert()` calls are present in the imported code.

## Known Issues

Unknown from initial import.

## Future Ideas

Unknown from initial import.
