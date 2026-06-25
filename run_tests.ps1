$ErrorActionPreference = "Stop"

python -m pytest --cov=stowage_optimizer --cov=app --cov-report=term-missing
