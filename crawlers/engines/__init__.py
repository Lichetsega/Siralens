"""Engines: one generic crawler per kind of source. Sources are configured in sources.yaml."""
from . import feed, html_portal, json_api, reliefweb, telegram

ENGINES = {
    "html": html_portal.run,
    "feed": feed.run,
    "telegram": telegram.run,
    "json_api": json_api.run,
    "reliefweb": reliefweb.run,
}
