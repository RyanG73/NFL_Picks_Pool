import os
import resend
from jinja2 import Environment, FileSystemLoader, select_autoescape

resend.api_key = os.environ.get("RESEND_API_KEY", "")

_template_env = Environment(
    loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), "..", "templates")),
    autoescape=select_autoescape(["html"]),
)

FROM = f"{os.environ.get('FROM_NAME', 'NFL Picks Pool')} <{os.environ.get('FROM_EMAIL', 'picks@example.com')}>"


def _render(template_name: str, **ctx) -> str:
    return _template_env.get_template(template_name).render(**ctx)


def send_weekly_spreads(players: list[dict], week: int, season: int, games: list[dict], standings: list[dict], prizes: list[str] | None = None) -> None:
    """Wednesday email: spreads live + last week results."""
    app_url = os.environ.get("APP_URL", "")
    for player in players:
        html = _render(
            "email/weekly_spreads.html",
            player=player,
            week=week,
            season=season,
            games=games,
            standings=standings,
            prizes=prizes or [],
            picks_url=f"{app_url}/p/{player['magic_token']}",
            app_url=app_url,
        )
        resend.Emails.send({
            "from": FROM,
            "to": player["email"],
            "subject": f"🏈 Week {week} Spreads Are Live — {season} NFL Picks Pool",
            "html": html,
        })


def send_reminder(player: dict, week: int) -> None:
    """Friday night: you haven't picked yet."""
    app_url = os.environ.get("APP_URL", "")
    html = _render(
        "email/reminder.html",
        player=player,
        week=week,
        picks_url=f"{app_url}/p/{player['magic_token']}",
    )
    resend.Emails.send({
        "from": FROM,
        "to": player["email"],
        "subject": f"⏰ Reminder: Week {week} picks due Saturday 11:59am ET",
        "html": html,
    })


def send_picks_reveal(players: list[dict], week: int, season: int) -> None:
    """Saturday after lock: picks are live."""
    if not players:
        return
    app_url = os.environ.get("APP_URL", "")
    html = _render(
        "email/picks_reveal.html",
        week=week,
        season=season,
        reveal_url=f"{app_url}/week/{week}",
        app_url=app_url,
    )
    to_addrs = [p["email"] for p in players]
    resend.Emails.send({
        "from": FROM,
        "to": to_addrs[0],
        "bcc": to_addrs[1:],
        "subject": f"👀 Week {week} Picks Are Live — {season} NFL Picks Pool",
        "html": html,
    })


def send_magic_link(player: dict) -> None:
    """Send (or resend) a player's magic link."""
    app_url = os.environ.get("APP_URL", "")
    html = _render(
        "email/magic_link.html",
        player=player,
        picks_url=f"{app_url}/p/{player['magic_token']}",
        app_url=app_url,
    )
    resend.Emails.send({
        "from": FROM,
        "to": player["email"],
        "subject": "🔗 Your NFL Picks Pool link",
        "html": html,
    })


def send_admin_alert(to: str, subject: str, body: str) -> None:
    """Send a plain-text alert to the admin (Ryan)."""
    html = f"<pre style='font-family:monospace'>{body}</pre>"
    resend.Emails.send({"from": FROM, "to": to, "subject": subject, "html": html})


def send_broadcast(players: list[dict], subject: str, body_html: str) -> None:
    """Mass-message all players."""
    if not players:
        return
    to_addrs = [p["email"] for p in players]
    resend.Emails.send({
        "from": FROM,
        "to": to_addrs[0],
        "bcc": to_addrs[1:],
        "subject": subject,
        "html": body_html,
    })
