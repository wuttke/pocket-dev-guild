"""Entry point: `uvicorn main:app --reload`."""

from pocket_dev_guild import create_app

app = create_app()
