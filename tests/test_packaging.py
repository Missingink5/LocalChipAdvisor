import tomllib
from pathlib import Path


def test_pyproject_registers_cli_console_script() -> None:
    project_root = Path(__file__).resolve().parents[1]

    with (project_root / "pyproject.toml").open("rb") as file:
        pyproject = tomllib.load(file)

    assert (
        pyproject["project"]["scripts"]["local-chip-advisor"]
        == "local_chip_advisor.cli:cli_entrypoint"
    )
