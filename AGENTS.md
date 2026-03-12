# Agent Instructions

- This repository tracks the API version in `backend/version.py`. The value of `__version__` is the single source of truth and is consumed by the FastAPI app for the OpenAPI banner.
- For every pull request, bump the patch version using `python scripts/bump_version.py` before committing changes. Do not edit the version string manually.
- If you introduce breaking changes, bump the minor or major version instead by passing `--part minor` or `--part major` to the bump script.
