"""Available scaffold commands; pipeline commands are added in later steps."""

import typer

from klegal_gold import __version__
from klegal_gold.config import ConfigurationError, configure_logging, load_settings
from klegal_gold.db.connection import database_available
from klegal_gold.operations import operations

app = typer.Typer(no_args_is_help=True, pretty_exceptions_enable=False)
app.add_typer(operations, name="ops")


@app.command()
def version() -> None:
    """Print the package version."""
    typer.echo(__version__)


@app.command()
def check_config() -> None:
    """Validate settings without printing their contents."""
    try:
        settings = load_settings()
        configure_logging(settings)
    except ConfigurationError:
        typer.echo("Configuration invalid", err=True)
        raise typer.Exit(1) from None
    typer.echo("Configuration valid")


@app.command()
def check_db() -> None:
    """Run a read-only PostgreSQL connectivity check."""
    try:
        available = database_available(load_settings())
    except ConfigurationError:
        available = False
    typer.echo("Database reachable" if available else "Database unavailable")
    if not available:
        raise typer.Exit(1)
