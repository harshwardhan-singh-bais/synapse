"""Allow running synapse as ``python -m synapse``."""
from synapse.cli.main import cli

if __name__ == "__main__":
    cli()
