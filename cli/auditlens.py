#!/usr/bin/env python3
"""AuditLens CLI — single-file, no codebase import.

Speaks to a running AuditLens API (FastAPI behind Caddy at /api/*) over
HTTPS or HTTP. Config lives in ~/.auditlens.conf and/or env vars.
"""
from __future__ import annotations

import configparser
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, NoReturn

import click
import httpx

CONFIG_PATH = Path.home() / ".auditlens.conf"
DEFAULT_URL = "http://localhost"
DEFAULT_PG_USER = "auditlens"
DEFAULT_PG_DB = "auditlens"
DEFAULT_COMPOSE = "~/AuditLens/docker-compose.prod.yml"

SIGNAL_CHOICES = ["action_required", "attention", "informational", "noise"]
WINDOW_CHOICES = ["5m", "15m", "30m", "1h", "2h", "4h", "12h", "24h", "7d", "30d"]


# ──────────── config / client helpers ────────────

def load_config() -> dict[str, str]:
    cfg: dict[str, str] = {
        "url": os.environ.get("AUDITLENS_URL", DEFAULT_URL),
        "pg_host": os.environ.get("AUDITLENS_PG_HOST", ""),
        "pg_user": os.environ.get("AUDITLENS_PG_USER", DEFAULT_PG_USER),
        "pg_db": os.environ.get("AUDITLENS_PG_DB", DEFAULT_PG_DB),
        "token": os.environ.get("AUDITLENS_TOKEN", ""),
        "compose_file": DEFAULT_COMPOSE,
    }
    if CONFIG_PATH.exists():
        parser = configparser.ConfigParser()
        parser.read(CONFIG_PATH)
        if parser.has_section("auditlens"):
            for k in cfg:
                if k in parser["auditlens"]:
                    cfg[k] = parser["auditlens"][k]
    return cfg


def save_config(updates: dict[str, str]) -> None:
    parser = configparser.ConfigParser()
    if CONFIG_PATH.exists():
        parser.read(CONFIG_PATH)
    if not parser.has_section("auditlens"):
        parser.add_section("auditlens")
    for k, v in updates.items():
        if v is not None:
            parser.set("auditlens", k, str(v))
    with open(CONFIG_PATH, "w") as fh:
        parser.write(fh)
    os.chmod(CONFIG_PATH, 0o600)


def make_client(cfg: dict[str, str]) -> httpx.Client:
    headers = {}
    if cfg.get("token"):
        headers["Authorization"] = f"Bearer {cfg['token']}"
    base = cfg["url"].rstrip("/")
    return httpx.Client(base_url=f"{base}/api", headers=headers, timeout=30.0)


# ──────────── formatting helpers ────────────

def encode_window(value: str) -> str:
    """Translate Nd → Nh for backend time_window regex ([1-9][0-9]*[mh]).

    The backend rejects 'Nd'; we do the same conversion the frontend does.
    """
    if not value:
        return value
    if value.endswith("d"):
        try:
            return f"{int(value[:-1]) * 24}h"
        except ValueError:
            pass
    return value


def fmt_time_local(ts: str | None) -> str:
    """Parse ISO timestamp, return local-tz 'Jun 03 11:44'."""
    if not ts:
        return ""
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%b %d %H:%M")
    except Exception:
        return ts


def style_signal(signal: str | None) -> str:
    if not signal:
        return "—"
    if signal == "action_required":
        return click.style(signal, fg="red")
    if signal == "attention":
        return click.style(signal, fg="yellow")
    if signal == "informational":
        return click.style(signal, fg="green")
    if signal == "noise":
        return click.style(signal, dim=True)
    return signal


def truncate(s: Any, width: int) -> str:
    if s is None:
        return ""
    s = str(s)
    if len(s) > width:
        return s[: width - 1] + "…"
    return s


def render_table(rows: list[dict[str, str]], columns: list[tuple[str, str, int]]) -> None:
    """Render a fixed-width table. columns: [(key, label, width), ...]."""
    header = "  ".join(label.ljust(width) for _, label, width in columns)
    click.echo(click.style(header, bold=True))
    click.echo("  ".join("-" * width for _, _, width in columns))
    for row in rows:
        cells = []
        for key, _, width in columns:
            val = row.get(key, "")
            # ANSI colour codes inflate len() — measure stripped width.
            stripped = click.unstyle(val) if isinstance(val, str) else str(val)
            display = val if isinstance(val, str) else str(val)
            pad = " " * max(0, width - len(stripped))
            cells.append(display + pad)
        click.echo("  ".join(cells))


def http_error_exit(exc: Exception) -> NoReturn:
    click.echo(click.style(f"Error: {exc}", fg="red"), err=True)
    sys.exit(1)


# ──────────── CLI ────────────

@click.group()
def cli() -> None:
    """AuditLens command-line interface."""


# ----- config -----

@cli.group()
def config() -> None:
    """Manage CLI configuration (~/.auditlens.conf)."""


@config.command("set")
@click.option("--url", help="Base URL of the AuditLens deployment (e.g. http://98.95.144.160).")
@click.option("--pg-host", help="Postgres host for direct queries (optional).")
@click.option("--pg-user", help="Postgres user (default: auditlens).")
@click.option("--pg-db", help="Postgres database (default: auditlens).")
@click.option("--token", help="Bearer token if API_AUTH_ENABLED=true.")
@click.option("--compose-file", help="Path to docker-compose.prod.yml on the deploy host.")
def config_set(
    url: str | None,
    pg_host: str | None,
    pg_user: str | None,
    pg_db: str | None,
    token: str | None,
    compose_file: str | None,
) -> None:
    """Persist CLI settings to ~/.auditlens.conf (chmod 600)."""
    updates = {
        "url": url,
        "pg_host": pg_host,
        "pg_user": pg_user,
        "pg_db": pg_db,
        "token": token,
        "compose_file": compose_file,
    }
    updates = {k: v for k, v in updates.items() if v is not None}
    if not updates:
        click.echo("No --options supplied. Nothing to write.")
        return
    save_config(updates)
    click.echo(f"Wrote {CONFIG_PATH}")
    for k, v in updates.items():
        if k == "token" and v:
            v = f"***{v[-4:]}"
        click.echo(f"  {k} = {v}")


@config.command("show")
def config_show() -> None:
    """Print resolved config (masks the token)."""
    cfg = load_config()
    for k, v in cfg.items():
        if k == "token" and v:
            v = f"***{v[-4:]}"
        click.echo(f"{k} = {v}")


# ----- events -----

@cli.group()
def events() -> None:
    """Browse, fetch, and export audit events."""


def _events_filter_params(
    signal: str | None, actor: str | None, since: str, limit: int
) -> dict[str, str]:
    params: dict[str, str] = {
        "limit": str(limit),
        "time_window": encode_window(since),
    }
    if signal:
        params["signal_type"] = signal
    if actor:
        params["actor"] = actor
    return params


@events.command("list")
@click.option("--signal", type=click.Choice(SIGNAL_CHOICES))
@click.option("--actor", help="Partial actor / email match (ILIKE on backend).")
@click.option("--since", default="24h", show_default=True, help="Time window (Nm/Nh/Nd).")
@click.option("--limit", default=20, type=click.IntRange(1, 200), show_default=True)
@click.option("--json", "json_output", is_flag=True, help="Raw JSON output.")
def events_list(
    signal: str | None,
    actor: str | None,
    since: str,
    limit: int,
    json_output: bool,
) -> None:
    """List recent events as a coloured table."""
    cfg = load_config()
    with make_client(cfg) as client:
        try:
            r = client.get("/events", params=_events_filter_params(signal, actor, since, limit))
            r.raise_for_status()
        except httpx.HTTPError as exc:
            http_error_exit(exc)
        data = r.json()
    items = data.get("items", [])
    if json_output:
        click.echo(json.dumps(items, indent=2, default=str))
        return
    if not items:
        click.echo("No events matched.")
        return
    rows = []
    for it in items:
        rows.append(
            {
                "time": fmt_time_local(it.get("timestamp")),
                "actor": truncate(it.get("actor_display_name") or it.get("actor") or "—", 28),
                "action": truncate(it.get("action") or "—", 30),
                "signal": style_signal(it.get("signal_type")),
                "reason": truncate(it.get("decision_reason") or "—", 22),
                "risk": it.get("risk_level") or "—",
            }
        )
    render_table(
        rows,
        [
            ("time", "Time", 12),
            ("actor", "Actor", 28),
            ("action", "Action", 30),
            ("signal", "Signal", 16),
            ("reason", "Reason", 22),
            ("risk", "Risk", 10),
        ],
    )
    total = data.get("total")
    suffix = f" of {total}" if total is not None else ""
    click.echo(f"\nShowing {len(items)}{suffix} matching events.")


@events.command("get")
@click.argument("event_id", type=int)
def events_get(event_id: int) -> None:
    """Fetch a single event by integer ID and print every field."""
    cfg = load_config()
    with make_client(cfg) as client:
        try:
            r = client.get(f"/events/{event_id}")
            r.raise_for_status()
        except httpx.HTTPError as exc:
            http_error_exit(exc)
        data = r.json()
    for key in sorted(data.keys()):
        val = data[key]
        if isinstance(val, (dict, list)):
            val = json.dumps(val, default=str)
        click.echo(f"{key}: {val}")


@events.command("export")
@click.option("--signal", type=click.Choice(SIGNAL_CHOICES))
@click.option("--actor")
@click.option("--since", default="24h", show_default=True)
@click.option("--limit", default=1000, type=click.IntRange(1, 50000), show_default=True)
@click.option("--format", "fmt", type=click.Choice(["csv", "json"]), default="csv", show_default=True)
@click.option("--out", type=click.Path(dir_okay=False, writable=True), default=None,
              help="Output file (default: stdout).")
def events_export(
    signal: str | None,
    actor: str | None,
    since: str,
    limit: int,
    fmt: str,
    out: str | None,
) -> None:
    """Stream events to CSV or JSON via /api/events/export."""
    cfg = load_config()
    params = _events_filter_params(signal, actor, since, limit)
    params["format"] = fmt
    with make_client(cfg) as client:
        try:
            with client.stream("GET", "/events/export", params=params) as r:
                r.raise_for_status()
                if out:
                    with open(out, "wb") as fh:
                        for chunk in r.iter_bytes():
                            fh.write(chunk)
                    click.echo(f"Wrote {out}", err=True)
                else:
                    for chunk in r.iter_bytes():
                        sys.stdout.buffer.write(chunk)
        except httpx.HTTPError as exc:
            http_error_exit(exc)


# ----- stats compare -----

@cli.group()
def stats() -> None:
    """Aggregate stats across periods."""


def _top(items: list[dict], key: str) -> str:
    if not items:
        return "—"
    first = items[0]
    name = first.get(key) or "—"
    count = first.get("count")
    return f"{name} ({count})" if count is not None else str(name)


@stats.command("compare")
@click.option("--period-a", default="24h", show_default=True)
@click.option("--period-b", default="7d", show_default=True)
def stats_compare(period_a: str, period_b: str) -> None:
    """Side-by-side stats for two time windows."""
    cfg = load_config()
    with make_client(cfg) as client:
        try:
            r = client.get(
                "/events/compare",
                params={"period_a": encode_window(period_a), "period_b": encode_window(period_b)},
            )
            r.raise_for_status()
        except httpx.HTTPError as exc:
            http_error_exit(exc)
        data = r.json()
    a, b = data["period_a"], data["period_b"]

    def sig(p: dict, key: str) -> str:
        return str(p.get("by_signal_type", {}).get(key, 0))

    metrics = [
        ("Total events", str(a["total"]), str(b["total"])),
        ("Action required", sig(a, "action_required"), sig(b, "action_required")),
        ("Attention", sig(a, "attention"), sig(b, "attention")),
        ("Informational", sig(a, "informational"), sig(b, "informational")),
        ("Noise", sig(a, "noise"), sig(b, "noise")),
        ("Top actor", _top(a["top_actors"], "name"), _top(b["top_actors"], "name")),
        ("Top action", _top(a["top_methods"], "action"), _top(b["top_methods"], "action")),
    ]
    label_a = f"Period A ({period_a})"
    label_b = f"Period B ({period_b})"
    name_w = max(len("Metric"), max(len(m[0]) for m in metrics))
    col_w = max(len(label_a), len(label_b), max(len(m[1]) for m in metrics), max(len(m[2]) for m in metrics))
    click.echo(click.style(
        f"{'Metric'.ljust(name_w)}  {label_a.ljust(col_w)}  {label_b.ljust(col_w)}",
        bold=True,
    ))
    click.echo("  ".join(["-" * name_w, "-" * col_w, "-" * col_w]))
    for metric, va, vb in metrics:
        click.echo(f"{metric.ljust(name_w)}  {va.ljust(col_w)}  {vb.ljust(col_w)}")


# ----- pipeline -----

@cli.group()
def pipeline() -> None:
    """Inspect pipeline health and Postgres internals."""


@pipeline.command("status")
def pipeline_status() -> None:
    """API health + recent ingest rate + last-event freshness."""
    cfg = load_config()
    base = cfg["url"].rstrip("/")
    # /health is exposed at root (Caddy maps it directly); doesn't need /api.
    try:
        h = httpx.get(f"{base}/health", timeout=10.0)
        api_line = f"{h.status_code} {h.reason_phrase}"
    except httpx.HTTPError as exc:
        api_line = f"unreachable ({exc})"

    last_5 = last_60 = "—"
    last_ts = None
    with make_client(cfg) as client:
        try:
            r = client.get("/events/compare", params={"period_a": "5m", "period_b": "60m"})
            r.raise_for_status()
            comp = r.json()
            last_5 = str(comp["period_a"]["total"])
            last_60 = str(comp["period_b"]["total"])
        except httpx.HTTPError as exc:
            click.echo(click.style(f"  compare endpoint error: {exc}", fg="red"), err=True)

        try:
            r = client.get("/events", params={"limit": 1, "time_window": "24h"})
            r.raise_for_status()
            items = r.json().get("items", [])
            last_ts = items[0]["timestamp"] if items else None
        except httpx.HTTPError:
            pass

    click.echo(click.style("Pipeline status", bold=True))
    click.echo(f"  API health     : {api_line}")
    if last_ts:
        try:
            ts_dt = datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
            now = datetime.now(ts_dt.tzinfo)
            mins_ago = int((now - ts_dt).total_seconds() // 60)
        except Exception:
            mins_ago = -1
        click.echo(f"  Last event     : {fmt_time_local(last_ts)} ({mins_ago} min ago)")
        if mins_ago > 30:
            click.echo(click.style(
                f"  WARNING        : pipeline silent for {mins_ago} minutes (threshold 30)",
                fg="red", bold=True,
            ))
    else:
        click.echo(click.style("  Last event     : none in last 24h", fg="red"))
    click.echo(f"  Events last 5m : {last_5}")
    click.echo(f"  Events last 1h : {last_60}")


@pipeline.command("indexes")
def pipeline_indexes() -> None:
    """List audit_events* indexes via `docker compose exec postgres psql`."""
    cfg = load_config()
    compose_file = os.path.expanduser(cfg.get("compose_file") or DEFAULT_COMPOSE)
    cmd = [
        "docker", "compose", "-f", compose_file, "exec", "-T", "postgres",
        "psql", "-U", cfg["pg_user"], "-d", cfg["pg_db"], "-c", r"\di audit_events*",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except FileNotFoundError:
        click.echo(click.style("docker not on PATH (run from the deploy host).", fg="red"), err=True)
        sys.exit(1)
    if result.returncode != 0:
        click.echo(click.style(f"psql failed: {result.stderr.strip()}", fg="red"), err=True)
        sys.exit(1)
    rows: list[dict[str, str]] = []
    for line in result.stdout.splitlines():
        if not line.startswith(" public"):
            continue
        parts = [p.strip() for p in line.split("|")]
        if len(parts) >= 5:
            rows.append({"name": parts[1], "type": parts[2], "table": parts[4]})
    if not rows:
        click.echo("No audit_events* indexes found.")
        click.echo(result.stdout)
        return
    name_w = max(20, max(len(r["name"]) for r in rows))
    table_w = max(15, max(len(r["table"]) for r in rows))
    click.echo(click.style(
        f"{'Index name'.ljust(name_w)}  {'Type'.ljust(8)}  {'Table'.ljust(table_w)}", bold=True,
    ))
    click.echo("  ".join(["-" * name_w, "-" * 8, "-" * table_w]))
    for r_ in rows:
        click.echo(f"{r_['name'].ljust(name_w)}  {r_['type'].ljust(8)}  {r_['table'].ljust(table_w)}")


# ----- alerts -----

@cli.group()
def alerts() -> None:
    """Notification destination tools."""


@alerts.command("test")
def alerts_test() -> None:
    """Fire a real test notification to every enabled Slack/Teams destination."""
    cfg = load_config()
    with make_client(cfg) as client:
        try:
            r = client.post("/settings/notifications/test", json={})
        except httpx.HTTPError as exc:
            http_error_exit(exc)
    if r.status_code == 404:
        click.echo("not available (POST /api/settings/notifications/test missing on this build)")
        sys.exit(2)
    if r.status_code in (401, 403):
        click.echo(click.style(
            f"auth required ({r.status_code}) — run `auditlens config set --token <admin-bearer>`",
            fg="yellow",
        ))
        sys.exit(1)
    try:
        data = r.json()
    except Exception:
        click.echo(r.text)
        return
    sent = data.get("sent_count", 0)
    errors = data.get("error_count", 0)
    fg = "green" if errors == 0 and sent > 0 else ("yellow" if errors == 0 else "red")
    click.echo(click.style(f"sent={sent}  errors={errors}", fg=fg, bold=True))
    for r_ in data.get("results", []):
        ok = r_.get("success", False)
        marker = click.style("✓", fg="green") if ok else click.style("✗", fg="red")
        name = r_.get("name") or r_.get("destination") or "?"
        msg = r_.get("message") or r_.get("error") or ""
        click.echo(f"  {marker} {name}  {msg}")


if __name__ == "__main__":
    cli()
