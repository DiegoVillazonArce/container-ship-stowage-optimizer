# Deployment and Local Operations

This document explains how to run, test, and deploy the project.

## Requirements

- Python 3.11 or newer.
- PowerShell on Windows for helper scripts.
- Dependencies from `requirements.txt`.

## Local Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -e .
```

## Run the App

```powershell
powershell -ExecutionPolicy Bypass -File .\run_app.ps1
```

The helper launches Streamlit with `app/main.py`.

## Run Tests

```powershell
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1
```

The test script runs the project test suite with coverage.

## Run Ruff

```powershell
python -m ruff check .
```

## Streamlit Community Cloud

The public app is deployed at:

[https://container-ship-stowage-optimizer.streamlit.app/](https://container-ship-stowage-optimizer.streamlit.app/)

Deployment prerequisites:

- repository pushed to GitHub;
- `requirements.txt` available at repository root;
- Streamlit entry point set to `app/main.py`;
- app secrets are not required;
- heavy MILP runs should use sensible time limits.

## Hosted Runtime Notes

Streamlit Community Cloud is suitable for demos, small scenarios, and moderate
heuristic runs. For larger MILP experiments, use local execution or strict time
limits.

Recommended hosted usage:

- Greedy for quick plans;
- GA for moderate scenarios;
- Local Search with bounded iterations;
- MILP only for small instances or short time-limited reference runs.

## Troubleshooting

### Streamlit duplicate element IDs

If two charts or tables render identical structures, Streamlit may require
explicit stable keys. The app uses explicit keys for repeated result charts,
tables, downloads, and learning-guide visuals.

### Arrow dataframe serialization warnings

Mixed-type dataframe columns can trigger Arrow compatibility warnings. UI helper
tables that mix labels, numbers, booleans, and strings should format display
values consistently.

### MILP takes too long

Reduce vessel size, container count, or MILP time limit. For larger scenarios,
use Greedy or GA and compare final metrics.

## Final Verification Checklist

Before publishing or presenting:

```powershell
python -m ruff check .
powershell -ExecutionPolicy Bypass -File .\run_tests.ps1
```

Then open the Streamlit app and verify:

- scenario configuration loads;
- at least one solver runs;
- result tables display;
- diagnostics render;
- 3D visualization renders;
- Academic guide opens;
- downloads work.

