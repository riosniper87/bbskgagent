"""Oracle connection env for HISIS (reuses AS as_analysis stack)."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def configure_oracle_env(
    *,
    project_root: Path | None = None,
    host: str = "127.0.0.1",
    port: str = "15211",
) -> Path:
    """Add AS to sys.path and set ORA_* for local SSH tunnel. Returns AS root."""
    os.environ.setdefault("AS_ANALYSIS", "Y")
    os.environ.setdefault("AS_ANALYSIS_USE_ORACLE", "Y")

    root = project_root or Path(__file__).resolve().parents[3]
    as_root = root.parent / "AS"
    src_path = as_root / "src"
    if not (src_path / "as_analysis").is_dir():
        raise RuntimeError(f"AS analysis package not found: {src_path / 'as_analysis'}")

    if str(src_path) not in sys.path:
        sys.path.insert(0, str(src_path))

    infra_env = as_root.parent / "infra" / ".env"
    if infra_env.is_file():
        os.environ.setdefault("AS_ANALYSIS_ENV_PATH", str(infra_env))

    os.environ.setdefault("ORACLE_CLIENT_LIB_DIR", r"C:\oracle\instantclient_23_0")
    os.environ["ORA_KRHIP_HOST"] = host
    os.environ["ORA_KRHIP_PORT"] = port
    return as_root


def sql_in_list(values: list[str]) -> str:
    return ", ".join("'" + v.replace("'", "''") + "'" for v in values)
