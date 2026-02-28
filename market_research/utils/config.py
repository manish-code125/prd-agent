import os
from pathlib import Path

from dotenv import load_dotenv
import typer


PROJECT_ROOT = Path(__file__).parent.parent.parent


def load_config() -> dict:
    """Load configuration from environment variables and .env file."""
    # Try cwd first, then project root
    for candidate in [Path.cwd() / ".env", PROJECT_ROOT / ".env"]:
        if candidate.exists():
            load_dotenv(candidate)
            break
    else:
        load_dotenv()

    return {
        "api_key": os.environ.get("ANTHROPIC_API_KEY", ""),
    }


def validate_config(config: dict) -> None:
    """Validate required configuration. Exit with helpful message if invalid."""
    if not config.get("api_key"):
        typer.echo(
            "Error: ANTHROPIC_API_KEY not found.\n"
            "Set it in a .env file or export it:\n"
            "  export ANTHROPIC_API_KEY='your-key-here'\n"
            "Get a key at: https://console.anthropic.com/settings/keys",
            err=True,
        )
        raise typer.Exit(code=1)
