"""Private migration subprocess entry point; invoked only while the lease is held."""
from tests.safety import install_test_safety, validate_test_database

install_test_safety()

import os
from pathlib import Path
from alembic import command
from alembic.config import Config


def main():
    validate_test_database(os.environ)
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    command.upgrade(config, "head")


if __name__ == "__main__":
    main()
