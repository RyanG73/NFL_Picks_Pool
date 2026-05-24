import html as _html
import os
import resend
from jinja2 import Environment, FileSystemLoader, select_autoescape

from api.lib.timewall import kickoff_time_et, kickoff_day_et, spread_fmt

resend.api_key = os.environ.get("RESEND_API_KEY", "")

_template_env = Environment(
    loader=FileSystemLoader(os.path.join(os.path.dirname(__file__), "..", "templates")),
    autoescape=select_autoescape(["html"]),
)
_template_env.filters["kickoff_et"] = kickoff_time_et
_template_env.filters["kickoff_day"] = kickoff_day_et
_template_env.filters["spread_fmt"] = spread_fmt

FROM = f"{os.environ.get('FROM_NAME', 'NFL Picks Pool')} <{os.environ.get('FROM_EMAIL', 'picks@example.com')}>"


def _render(template_name: str, **ctx) -> str:
    return _template_env.get_template(template_name).render(**ctx)


def send_weekly_spreads(players: list[dict], week: int, season: int, games: list[dict], standings: list[dict], prizes: list[str] | None = None) -> None:
    """Wednesday email: spreads live + last week results."""
    app_url = os.environ.get("APP_URL", "")
    errors: list[tuple[str, str]] = []
    for player in players:
        try:
            body = _render(
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
                "html": body,
            })
        except Exception as exc:
            errors.append((player["email"], str(exc)))
    if errors:
        print(f"[email_send] send_weekly_spreads: {len(errors)} error(s):")
        for addr, err in errors:
            print(f"  {addr}: {err}")


def send_reminder(player: dict, week: int, season: int = 0) -> None:
    """Friday night: you haven't picked yet."""
    app_url = os.environ.get("APP_URL", "")
    if not season:
        season = int(os.environ.get("CURRENT_SEASON", 2026))
    html = _render(
        "email/reminder.html",
        player=player,
        week=week,
        season=season,
        app_url=app_url,
        picks_url=f"{app_url}/p/{player['magic_token']}",
    )
    resend.Emails.send({
        "from": FROM,
        "to": player["email"],
        "subject": f"⏰ Reminder: Week {week} picks due Saturday noon ET",
        "html": html,
    })


def send_picks_reveal(players: list[dict], week: int, season: int) -> None:
    """Saturday after lock: picks are live."""
    if not players:
        return
    app_url = os.environ.get("APP_URL", "")
    reveal_url = f"{app_url}/week/{week}"
    body = _render(
        "email/picks_reveal.html",
        week=week,
        season=season,
        reveal_url=reveal_url,
        picks_url=reveal_url,  # footer "Your picks link" → this week's reveal
        app_url=app_url,
    )
    to_addrs = [p["email"] for p in players]
    payload: dict = {
        "from": FROM,
        "to": to_addrs[0],
        "subject": f"👀 Week {week} Picks Are Live — {season} NFL Picks Pool",
        "html": body,
    }
    if len(to_addrs) > 1:
        payload["bcc"] = to_addrs[1:]
    resend.Emails.send(payload)


def send_magic_link(player: dict, season: int = 0) -> None:
    """Send (or resend) a player's magic link."""
    app_url = os.environ.get("APP_URL", "")
    if not season:
        season = int(os.environ.get("CURRENT_SEASON", 2026))
    html = _render(
        "email/magic_link.html",
        player=player,
        season=season,
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
    body_html = f"<pre style='font-family:monospace'>{_html.escape(body)}</pre>"
    resend.Emails.send({"from": FROM, "to": to, "subject": subject, "html": body_html})


def send_broadcast(players: list[dict], subject: str, body_html: str) -> None:
    """Mass-message all players."""
    if not players:
        return
    # Auto-wrap plain text so email clients don't collapse everything to one line
    if "<" not in body_html:
        body_html = "<p>" + body_html.replace("\n\n", "</p><p>").replace("\n", "<br>") + "</p>"
    to_addrs = [p["email"] for p in players]
    payload: dict = {
        "from": FROM,
        "to": to_addrs[0],
        "subject": subject,
        "html": body_html,
    }
    if len(to_addrs) > 1:
        payload["bcc"] = to_addrs[1:]
    resend.Emails.send(payload)
