#!/usr/bin/env python3
"""
Export the cached VRCX mutual friend network into a GEXF graph file.
Windows default database path: %APPDATA%\\VRCX\\VRCX.sqlite3
Note: Relies on the VRCX local database. Requires VRCX Stable 2025.12.06 or later. Manually execute "Start Fetch" under "Mutual Friend Network" on the client's Chart page before exporting.
Windows 默认数据库路径：%APPDATA%\\VRCX\\VRCX.sqlite3
注意：依托 VRCX 本地数据库，需使用 VRCX Stable 2025.12.06 或更高版本 并手动在客户端 Chart 页面的 Mutual Friend Network 下执行 Start Fetch 后再导出。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import math
import os
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set, Tuple
from xml.sax.saxutils import quoteattr

EXCLUDED_IDS = {"usr_00000000-0000-0000-0000-000000000000"}
HALFLIFE_DEFAULT_DAYS = 120


class ExportError(RuntimeError):
    """Raised when the exporter cannot proceed."""


class NodeData:
    """Data structure for a node in the graph."""

    def __init__(self, user_id: str):
        self.id = user_id
        self.type = "friend"
        self.display_name = ""
        self.trust_level = ""
        self.meet_count = 0
        self.meet_count_7d = 0
        self.meet_count_30d = 0
        self.play_time = 0.0
        self.play_time_7d = 0.0
        self.play_time_30d = 0.0
        self.days_known = 0
        self.relationship_strength = 0.0
        self.recent_intimacy = 0.0
        self.effective_hours = 0.0
        self.retention_rate = 0.0
        self.life_share = 0.0
        self.is_hidden_friend = False
        self.recent_intimacy_30d = 0.0
        self.recent_intimacy_60d = 0.0
        self.recent_intimacy_90d = 0.0
        # New fields for V2 algorithm
        self.active_days = 0
        self.interaction_count = 0
        self.connections = 0
        self._first_met: Optional[_dt.datetime] = None
        self._sessions: List[Tuple[_dt.datetime, float]] = []
        self._daily_hours: Dict[str, float] = {}  # day string -> hours


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Convert the cached VRCX mutual friend network into a GEXF file "
            "that can be imported into tools such as Gephi."
        )
    )
    parser.add_argument(
        "--db",
        default="VRCX.sqlite3",
        help="Path to the VRCX sqlite database (default: %(default)s).",
    )
    parser.add_argument(
        "--win", action="store_true", help="Use the default Windows VRCX DB path."
    )
    parser.add_argument(
        "--output",
        default="mutual_graph.gexf",
        help="Destination GEXF file path (default: %(default)s).",
    )
    parser.add_argument(
        "--prefix", help="Optional table prefix. Auto-detected if omitted."
    )
    parser.add_argument(
        "--halflife",
        type=int,
        default=HALFLIFE_DEFAULT_DAYS,
        help=f"Decay half-life in days (default: {HALFLIFE_DEFAULT_DAYS}).",
    )
    return parser.parse_args()


def _quote_table_name(name: str) -> str:
    if not name or any(
        c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_"
        for c in name
    ):
        raise ExportError(f"Unsafe table name detected: {name!r}")
    return name


def _normalize_prefix(value: str) -> str:
    for suffix in ("_mutual_graph_links", "_mutual_graph_friends"):
        if value.endswith(suffix):
            return value[: -len(suffix)]
    return value


def _detect_prefix(conn: sqlite3.Connection, explicit_prefix: str | None) -> str:
    if explicit_prefix:
        return _normalize_prefix(explicit_prefix)
    rows = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE ?",
        ("%mutual_graph_links",),
    ).fetchall()
    matches = sorted(
        {
            r[0][: -len("_mutual_graph_links")]
            for r in rows
            if r[0].endswith("_mutual_graph_links")
        }
    )
    if not matches:
        raise ExportError("Could not find any *_mutual_graph_links tables.")
    if len(matches) > 1:
        raise ExportError(
            f"Multiple datasets found. Use --prefix. Detected: {', '.join(matches)}"
        )
    return matches[0]


def _resolve_db_path(args: argparse.Namespace) -> Path:
    if args.win:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise ExportError("APPDATA is not set.")
        path = Path(appdata) / "VRCX" / "VRCX.sqlite3"
        if not path.exists():
            raise ExportError(f"Default Windows DB not found: {path}")
        return path
    return Path(args.db).expanduser()


def _load_friend_info(
    conn: sqlite3.Connection, prefix: str
) -> Dict[str, Tuple[str, str]]:
    """Load friends from friend_log_current. Only these are valid nodes."""
    table = _quote_table_name(f"{prefix}_friend_log_current")
    try:
        rows = conn.execute(
            f"SELECT user_id, display_name, trust_level FROM {table}"
        ).fetchall()
    except sqlite3.OperationalError:
        rows = conn.execute(f"SELECT user_id, display_name, '' FROM {table}").fetchall()
    return {
        r[0]: (r[1] or "", r[2] or "")
        for r in rows
        if r[0] and r[0] not in EXCLUDED_IDS
    }


def _load_edges(
    conn: sqlite3.Connection, prefix: str, valid_ids: Set[str]
) -> List[Tuple[str, str]]:
    """Load edges, keeping only those where BOTH ends are in valid_ids (friend_log_current)."""
    table = _quote_table_name(f"{prefix}_mutual_graph_links")
    rows = conn.execute(f"SELECT friend_id, mutual_id FROM {table}").fetchall()
    edges: List[Tuple[str, str]] = []
    for friend_id, mutual_id in rows:
        if (
            friend_id
            and mutual_id
            and friend_id in valid_ids
            and mutual_id in valid_ids
        ):
            edges.append((friend_id, mutual_id))
    return edges


def _get_db_max_time(conn: sqlite3.Connection) -> _dt.datetime:
    try:
        row = conn.execute("SELECT MAX(created_at) FROM gamelog_join_leave").fetchone()
        if row and row[0]:
            return _dt.datetime.fromisoformat(row[0].replace("Z", "+00:00"))
    except (sqlite3.OperationalError, ValueError):
        pass
    return _dt.datetime.now(_dt.timezone.utc)


def _load_play_data(
    conn: sqlite3.Connection, valid_ids: Set[str], now: _dt.datetime
) -> Dict[str, NodeData]:
    """Load play data ONLY for valid friend IDs."""
    nodes: Dict[str, NodeData] = {uid: NodeData(uid) for uid in valid_ids}

    try:
        rows = conn.execute("""
            SELECT user_id, created_at, time
            FROM gamelog_join_leave
            WHERE type = 'OnPlayerLeft' AND user_id IS NOT NULL AND user_id != ''
        """).fetchall()
    except sqlite3.OperationalError:
        return nodes

    now_ts = now.timestamp()
    ts_7d = now_ts - 7 * 86400
    ts_30d = now_ts - 30 * 86400

    for user_id, created_at, duration_ms in rows:
        if user_id not in nodes:
            continue

        node = nodes[user_id]
        try:
            ts = _dt.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            ts_epoch = ts.timestamp()
        except (ValueError, AttributeError):
            continue

        duration_s = max(0, (duration_ms or 0) / 1000.0)
        duration_hours = duration_s / 3600.0

        if node._first_met is None or ts < node._first_met:
            node._first_met = ts
        node._sessions.append((ts, duration_s))

        day_str = ts.strftime("%Y-%m-%d")
        node._daily_hours[day_str] = node._daily_hours.get(day_str, 0) + duration_hours

        if duration_s > 0:
            node.interaction_count += 1

        node.meet_count += 1
        node.play_time += duration_s

        if ts_epoch >= ts_7d:
            node.meet_count_7d += 1
            node.play_time_7d += duration_s
        if ts_epoch >= ts_30d:
            node.meet_count_30d += 1
            node.play_time_30d += duration_s

    for node in nodes.values():
        node.active_days = len(node._daily_hours)

    return nodes


def _load_connections(
    conn: sqlite3.Connection, prefix: str, nodes: Dict[str, NodeData]
) -> None:
    """Load mutual friend connection counts for each node."""
    table = _quote_table_name(f"{prefix}_mutual_graph_links")
    try:
        rows = conn.execute(
            f"SELECT friend_id, COUNT(*) as cnt FROM {table} GROUP BY friend_id"
        ).fetchall()
        for user_id, cnt in rows:
            if user_id in nodes:
                nodes[user_id].connections = cnt
    except sqlite3.OperationalError:
        pass


def _get_my_recent_hours(
    conn: sqlite3.Connection, now: _dt.datetime, recent_days: int
) -> float:
    """Get user's own recent online hours from gamelog_location."""
    try:
        now_str = now.strftime("%Y-%m-%d")
        row = conn.execute(f"""
            SELECT SUM(CASE WHEN time > 0 THEN time ELSE 0 END) / 3600000.0
            FROM gamelog_location
            WHERE created_at >= datetime('{now_str}', '-{recent_days} days')
        """).fetchone()
        return row[0] if row and row[0] else 0.0
    except sqlite3.OperationalError:
        return 0.0


def _get_total_days(conn: sqlite3.Connection) -> int:
    """Get total days range from gamelog_join_leave."""
    try:
        row = conn.execute("""
            SELECT julianday(MAX(date(created_at))) - julianday(MIN(date(created_at))) + 1
            FROM gamelog_join_leave
        """).fetchone()
        return max(1, int(row[0])) if row and row[0] else 1
    except sqlite3.OperationalError:
        return 1


def _detect_hidden_friends(
    nodes: Dict[str, NodeData], edges: List[Tuple[str, str]]
) -> None:
    adjacency: Dict[str, Set[str]] = {}
    for src, tgt in edges:
        adjacency.setdefault(src, set()).add(tgt)
        adjacency.setdefault(tgt, set()).add(src)

    for user_id, node in nodes.items():
        if node.meet_count > 0 and user_id not in adjacency:
            node.is_hidden_friend = True


def _calculate_metrics(
    nodes: Dict[str, NodeData],
    now: _dt.datetime,
    halflife_days: int,
    total_days: int,
    my_recent_hours_30d: float,
    my_recent_hours_60d: float,
    my_recent_hours_90d: float,
) -> None:
    now_ts = now.timestamp()
    now_str = now.strftime("%Y-%m-%d")

    for node in nodes.values():
        if node._first_met:
            node.days_known = int((now - node._first_met).total_seconds() / 86400)

    for node in nodes.values():
        effective = 0.0
        total = 0.0
        for day_str, hours in node._daily_hours.items():
            try:
                day_date = _dt.datetime.strptime(day_str, "%Y-%m-%d")
                days_ago = (now.replace(tzinfo=None) - day_date).days
            except ValueError:
                days_ago = 0
            weight = 2 ** (-days_ago / halflife_days)
            effective += hours * weight
            total += hours
        node.effective_hours = effective
        node.retention_rate = effective / total if total > 0 else 0

    all_effective_hours: List[float] = []
    all_total_hours: List[float] = []
    all_avg_durations: List[float] = []
    all_connections: List[int] = []

    for node in nodes.values():
        if node.play_time > 0:
            all_effective_hours.append(node.effective_hours)
            all_total_hours.append(node.play_time / 3600.0)
            if node.interaction_count > 0:
                all_avg_durations.append(
                    (node.play_time / 3600.0) / node.interaction_count
                )
        if node.connections > 0:
            all_connections.append(node.connections)

    all_effective_hours.sort()
    all_total_hours.sort()
    all_avg_durations.sort()
    all_connections.sort()

    median_avg_duration = (
        all_avg_durations[len(all_avg_durations) // 2] if all_avg_durations else 1.0
    )
    hours_p70 = (
        all_total_hours[int(len(all_total_hours) * 0.7)] if all_total_hours else 0
    )
    meets_p70 = (
        sorted([n.meet_count for n in nodes.values() if n.meet_count > 0])[
            int(len([n for n in nodes.values() if n.meet_count > 0]) * 0.7)
        ]
        if any(n.meet_count > 0 for n in nodes.values())
        else 0
    )

    def percentile_rank(value: float, sorted_values: Sequence[float]) -> float:
        if not sorted_values:
            return 0.0
        count_below = sum(1 for v in sorted_values if v < value)
        return count_below / len(sorted_values)

    def sigmoid(x: float, k: float) -> float:
        if k <= 0:
            return 0.5
        return x / (x + k)

    for node in nodes.values():
        if node.play_time <= 0:
            continue

        depth_percentile = percentile_rank(node.effective_hours, all_effective_hours)
        depth_score = depth_percentile * 40

        total_hours = node.play_time / 3600.0
        avg_duration = (
            total_hours / node.interaction_count if node.interaction_count > 0 else 0
        )
        quality_score = sigmoid(avg_duration, median_avg_duration) * 25

        stability_ratio = node.active_days / total_days if total_days > 0 else 0
        stability_score = math.sqrt(min(stability_ratio, 1)) * 20

        bond_score = 7.5
        if node.connections > 0:
            bond_percentile = percentile_rank(node.connections, all_connections)
            bond_score = bond_percentile * 15
        else:
            high_interaction = total_hours > hours_p70 or node.meet_count > meets_p70
            if high_interaction:
                node.is_hidden_friend = True
                bond_score = depth_percentile * 15

        node.relationship_strength = (
            depth_score + quality_score + stability_score + bond_score
        )

    for window_days, attr_name, my_hours in [
        (30, "recent_intimacy_30d", my_recent_hours_30d),
        (60, "recent_intimacy_60d", my_recent_hours_60d),
        (90, "recent_intimacy_90d", my_recent_hours_90d),
    ]:
        window_start = now_ts - window_days * 86400
        recent_data: List[Tuple[str, float, int]] = []

        for node in nodes.values():
            recent_hours = sum(
                d / 3600.0 for ts, d in node._sessions if ts.timestamp() >= window_start
            )
            recent_meets = sum(
                1 for ts, _ in node._sessions if ts.timestamp() >= window_start
            )
            recent_data.append((node.id, recent_hours, recent_meets))

        all_recent_hours = sorted([h for _, h, _ in recent_data if h > 0])
        all_recent_meets = sorted([m for _, _, m in recent_data if m > 0])
        all_life_shares = (
            sorted([h / my_hours for _, h, _ in recent_data if h > 0 and my_hours > 0])
            if my_hours > 0
            else []
        )
        median_life_share = (
            all_life_shares[len(all_life_shares) // 2] if all_life_shares else 0.01
        )

        for uid, recent_hours, recent_meets in recent_data:
            node = nodes[uid]
            if recent_hours <= 0:
                setattr(node, attr_name, 0.0)
                if window_days == 30:
                    node.life_share = 0.0
                continue

            time_score = percentile_rank(recent_hours, all_recent_hours) * 40
            freq_score = percentile_rank(recent_meets, all_recent_meets) * 30

            life_share = recent_hours / my_hours if my_hours > 0 else 0
            share_score = sigmoid(life_share, max(median_life_share, 0.01)) * 30

            setattr(node, attr_name, time_score + freq_score + share_score)
            if window_days == 30:
                node.life_share = life_share

    for node in nodes.values():
        node.recent_intimacy = node.recent_intimacy_30d


def _build_gexf(
    nodes: Dict[str, NodeData],
    edges: List[Tuple[str, str]],
    friend_info: Dict[str, Tuple[str, str]],
) -> str:
    timestamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")

    lines: List[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gexf xmlns="http://www.gexf.net/1.3draft" version="1.3">',
        f'  <meta lastmodifieddate="{timestamp}">',
        "    <creator>VRCX Mutual Graph Exporter</creator>",
        "    <description>Mutual friend network exported from VRCX</description>",
        "  </meta>",
        '  <graph mode="static" defaultedgetype="undirected">',
        '    <attributes class="node" mode="static">',
        '      <attribute id="0" title="type" type="string"/>',
        '      <attribute id="1" title="displayName" type="string"/>',
        '      <attribute id="2" title="trustLevel" type="string"/>',
        '      <attribute id="3" title="meetCount" type="integer"/>',
        '      <attribute id="4" title="meetCount7d" type="integer"/>',
        '      <attribute id="5" title="meetCount30d" type="integer"/>',
        '      <attribute id="6" title="playTime" type="float"/>',
        '      <attribute id="7" title="playTime7d" type="float"/>',
        '      <attribute id="8" title="playTime30d" type="float"/>',
        '      <attribute id="9" title="daysKnown" type="integer"/>',
        '      <attribute id="10" title="relationshipStrength" type="float"/>',
        '      <attribute id="11" title="recentIntimacy" type="float"/>',
        '      <attribute id="12" title="effectiveHours" type="float"/>',
        '      <attribute id="13" title="retentionRate" type="float"/>',
        '      <attribute id="14" title="lifeShare" type="float"/>',
        '      <attribute id="15" title="isHiddenFriend" type="boolean"/>',
        '      <attribute id="16" title="recentIntimacy30d" type="float"/>',
        '      <attribute id="17" title="recentIntimacy60d" type="float"/>',
        '      <attribute id="18" title="recentIntimacy90d" type="float"/>',
        "    </attributes>",
        "    <nodes>",
    ]

    for node_id in sorted(nodes.keys()):
        node = nodes[node_id]
        display_name, trust_level = friend_info.get(node_id, ("", ""))
        label = display_name or node_id

        lines.append(f"      <node id={quoteattr(node_id)} label={quoteattr(label)}>")
        lines.append("        <attvalues>")
        lines.append(f'          <attvalue for="0" value={quoteattr(node.type)} />')
        lines.append(f'          <attvalue for="1" value={quoteattr(display_name)} />')
        lines.append(f'          <attvalue for="2" value={quoteattr(trust_level)} />')
        lines.append(f'          <attvalue for="3" value="{node.meet_count}" />')
        lines.append(f'          <attvalue for="4" value="{node.meet_count_7d}" />')
        lines.append(f'          <attvalue for="5" value="{node.meet_count_30d}" />')
        lines.append(f'          <attvalue for="6" value="{node.play_time:.2f}" />')
        lines.append(f'          <attvalue for="7" value="{node.play_time_7d:.2f}" />')
        lines.append(f'          <attvalue for="8" value="{node.play_time_30d:.2f}" />')
        lines.append(f'          <attvalue for="9" value="{node.days_known}" />')
        lines.append(
            f'          <attvalue for="10" value="{node.relationship_strength:.2f}" />'
        )
        lines.append(
            f'          <attvalue for="11" value="{node.recent_intimacy:.2f}" />'
        )
        lines.append(
            f'          <attvalue for="12" value="{node.effective_hours:.2f}" />'
        )
        lines.append(
            f'          <attvalue for="13" value="{node.retention_rate:.4f}" />'
        )
        lines.append(f'          <attvalue for="14" value="{node.life_share:.4f}" />')
        lines.append(
            f'          <attvalue for="15" value="{str(node.is_hidden_friend).lower()}" />'
        )
        lines.append(
            f'          <attvalue for="16" value="{node.recent_intimacy_30d:.2f}" />'
        )
        lines.append(
            f'          <attvalue for="17" value="{node.recent_intimacy_60d:.2f}" />'
        )
        lines.append(
            f'          <attvalue for="18" value="{node.recent_intimacy_90d:.2f}" />'
        )
        lines.append("        </attvalues>")
        lines.append("      </node>")

    lines.append("    </nodes>")
    lines.append("    <edges>")
    for idx, (src, tgt) in enumerate(edges):
        lines.append(
            f'      <edge id="{idx}" source={quoteattr(src)} target={quoteattr(tgt)} />'
        )
    lines.append("    </edges>")
    lines.append("  </graph>")
    lines.append("</gexf>")
    return "\n".join(lines)


def main() -> None:
    args = _parse_args()
    db_path = _resolve_db_path(args)
    if not db_path.exists():
        raise ExportError(f"Database file not found: {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        prefix = _detect_prefix(conn, args.prefix)
        print(f"Using prefix: {prefix}")

        friend_info = _load_friend_info(conn, prefix)
        valid_ids = set(friend_info.keys())
        print(f"Found {len(valid_ids)} friends in friend_log_current")

        edges = _load_edges(conn, prefix, valid_ids)
        now = _get_db_max_time(conn)
        print(f"Database time reference: {now.isoformat()}")

        nodes = _load_play_data(conn, valid_ids, now)
        _load_connections(conn, prefix, nodes)

        total_days = _get_total_days(conn)
        my_recent_hours_30d = _get_my_recent_hours(conn, now, 30)
        my_recent_hours_60d = _get_my_recent_hours(conn, now, 60)
        my_recent_hours_90d = _get_my_recent_hours(conn, now, 90)
        print(
            f"Total days: {total_days}, My recent hours (30d): {my_recent_hours_30d:.1f}h"
        )
    finally:
        conn.close()

    _detect_hidden_friends(nodes, edges)
    _calculate_metrics(
        nodes,
        now,
        args.halflife,
        total_days,
        my_recent_hours_30d,
        my_recent_hours_60d,
        my_recent_hours_90d,
    )

    gexf_text = _build_gexf(nodes, edges, friend_info)
    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(gexf_text, encoding="utf-8")

    hidden_count = sum(1 for n in nodes.values() if n.is_hidden_friend)
    print(f"Exported {len(nodes)} friends and {len(edges)} edges to {output_path}")
    if hidden_count > 0:
        print(f"Detected {hidden_count} potential hidden friends")


if __name__ == "__main__":
    try:
        main()
    except ExportError as exc:
        raise SystemExit(f"error: {exc}") from exc
