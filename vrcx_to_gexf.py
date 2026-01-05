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
from typing import Dict, List, Optional, Sequence, Tuple
from xml.sax.saxutils import quoteattr

# IDs that should be excluded from export (e.g. placeholder/hidden mutuals)
EXCLUDED_IDS = {"usr_00000000-0000-0000-0000-000000000000"}

# Algorithm constants (matching ALGORITHM_DESIGN.md)
HALFLIFE_DEFAULT_DAYS = 120  # Decay half-life in days
RECENT_WINDOW_DAYS = 30  # Recent intimacy window
HOURS_PER_DAY = 24


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
        self.play_time = 0.0  # seconds
        self.play_time_7d = 0.0
        self.play_time_30d = 0.0
        self.days_known = 0
        self.relationship_strength = 0.0
        self.recent_intimacy = 0.0
        self.effective_hours = 0.0  # seconds
        self.retention_rate = 0.0
        self.life_share = 0.0
        self.is_hidden_friend = False
        self.recent_intimacy_30d = 0.0
        self.recent_intimacy_60d = 0.0
        self.recent_intimacy_90d = 0.0
        # Internal calculation fields
        self._first_met: Optional[_dt.datetime] = None
        self._sessions: List[
            Tuple[_dt.datetime, float]
        ] = []  # (timestamp, duration_seconds)


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
        "--win",
        action="store_true",
        help="Use the default Windows VRCX DB path (%APPDATA%\\VRCX\\VRCX.sqlite3).",
    )
    parser.add_argument(
        "--output",
        default="mutual_graph.gexf",
        help="Destination GEXF file path (default: %(default)s).",
    )
    parser.add_argument(
        "--prefix",
        help=(
            "Optional table prefix (e.g. usr670fcf3665cb48b986d4018b837d6fed). "
            "When omitted the exporter will try to detect it automatically."
        ),
    )
    parser.add_argument(
        "--halflife",
        type=int,
        default=HALFLIFE_DEFAULT_DAYS,
        help=f"Decay half-life in days for relationship strength (default: {HALFLIFE_DEFAULT_DAYS}).",
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
    suffixes = (
        "_mutual_graph_links",
        "_mutual_graph_friends",
    )
    for suffix in suffixes:
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
    matches: List[str] = []
    for (table_name,) in rows:
        if table_name.endswith("_mutual_graph_links"):
            matches.append(table_name[: -len("_mutual_graph_links")])
    unique_matches = sorted(set(matches))
    if not unique_matches:
        raise ExportError(
            "Could not find any *_mutual_graph_links tables in the database."
        )
    if len(unique_matches) > 1:
        raise ExportError(
            "Multiple mutual graph datasets found. Please specify one with --prefix. "
            f"Detected prefixes: {', '.join(unique_matches)}"
        )
    return unique_matches[0]


def _resolve_db_path(args: argparse.Namespace) -> Path:
    if args.win:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise ExportError(
                "APPDATA is not set; cannot resolve Windows default DB path."
            )
        path = Path(appdata) / "VRCX" / "VRCX.sqlite3"
        if not path.exists():
            raise ExportError(f"Default Windows DB not found: {path}")
        return path
    return Path(args.db).expanduser()


def _load_friend_ids(conn: sqlite3.Connection, prefix: str) -> Sequence[str]:
    table = _quote_table_name(f"{prefix}_mutual_graph_friends")
    rows = conn.execute(f"SELECT friend_id FROM {table}").fetchall()
    return [row[0] for row in rows if row[0]]


def _load_edges(conn: sqlite3.Connection, prefix: str) -> List[Tuple[str, str]]:
    table = _quote_table_name(f"{prefix}_mutual_graph_links")
    rows = conn.execute(f"SELECT friend_id, mutual_id FROM {table}").fetchall()
    edges: List[Tuple[str, str]] = []
    for friend_id, mutual_id in rows:
        if friend_id and mutual_id:
            if friend_id in EXCLUDED_IDS or mutual_id in EXCLUDED_IDS:
                continue
            edges.append((friend_id, mutual_id))
    return edges


def _load_friend_info(
    conn: sqlite3.Connection, prefix: str
) -> Dict[str, Tuple[str, str]]:
    """Load display_name and trust_level for friends.
    Returns: {user_id: (display_name, trust_level)}
    """
    table = _quote_table_name(f"{prefix}_friend_log_current")
    try:
        rows = conn.execute(
            f"SELECT user_id, display_name, trust_level FROM {table}"
        ).fetchall()
    except sqlite3.OperationalError:
        # Fallback if trust_level column doesn't exist
        rows = conn.execute(f"SELECT user_id, display_name, '' FROM {table}").fetchall()

    result: Dict[str, Tuple[str, str]] = {}
    for user_id, display_name, trust_level in rows:
        if user_id:
            result[user_id] = (display_name or "", trust_level or "")
    return result


def _get_db_max_time(conn: sqlite3.Connection) -> _dt.datetime:
    """Get the maximum created_at timestamp from gamelog_join_leave as 'now'."""
    try:
        row = conn.execute("SELECT MAX(created_at) FROM gamelog_join_leave").fetchone()
        if row and row[0]:
            return _dt.datetime.fromisoformat(row[0].replace("Z", "+00:00"))
    except (sqlite3.OperationalError, ValueError):
        pass
    return _dt.datetime.now(_dt.timezone.utc)


def _load_play_data(
    conn: sqlite3.Connection, friend_ids: Sequence[str], now: _dt.datetime
) -> Dict[str, NodeData]:
    """Load play data from gamelog_join_leave.
    Returns: {user_id: NodeData with play stats populated}
    """
    nodes: Dict[str, NodeData] = {}

    # Initialize nodes for all friends
    for fid in friend_ids:
        if fid not in EXCLUDED_IDS:
            nodes[fid] = NodeData(fid)

    try:
        # Query all OnPlayerLeft events (which contain duration in 'time' field as milliseconds)
        rows = conn.execute("""
            SELECT user_id, created_at, time
            FROM gamelog_join_leave
            WHERE type = 'OnPlayerLeft' AND user_id IS NOT NULL
        """).fetchall()
    except sqlite3.OperationalError:
        return nodes

    # Calculate time boundaries
    now_ts = now.timestamp()
    ts_7d = now_ts - 7 * 86400
    ts_30d = now_ts - 30 * 86400
    ts_60d = now_ts - 60 * 86400
    ts_90d = now_ts - 90 * 86400

    for user_id, created_at, duration_ms in rows:
        if not user_id or user_id in EXCLUDED_IDS:
            continue
        if user_id not in nodes:
            # This user is a mutual but not a direct friend
            nodes[user_id] = NodeData(user_id)
            nodes[user_id].type = "mutual"

        node = nodes[user_id]

        # Parse timestamp
        try:
            ts = _dt.datetime.fromisoformat(created_at.replace("Z", "+00:00"))
            ts_epoch = ts.timestamp()
        except (ValueError, AttributeError):
            continue

        # Duration in seconds (handle negative values as 0)
        duration_s = max(0, (duration_ms or 0) / 1000.0)

        # Track first met date
        if node._first_met is None or ts < node._first_met:
            node._first_met = ts

        # Store session for decay calculation
        node._sessions.append((ts, duration_s))

        # Accumulate stats
        node.meet_count += 1
        node.play_time += duration_s

        if ts_epoch >= ts_7d:
            node.meet_count_7d += 1
            node.play_time_7d += duration_s

        if ts_epoch >= ts_30d:
            node.meet_count_30d += 1
            node.play_time_30d += duration_s

    return nodes


def _detect_hidden_friends(
    conn: sqlite3.Connection,
    prefix: str,
    nodes: Dict[str, NodeData],
    edges: List[Tuple[str, str]],
) -> None:
    """Detect friends who may have hidden their mutual friend relationships."""
    # Build adjacency from edges
    adjacency: Dict[str, set] = {}
    for src, tgt in edges:
        adjacency.setdefault(src, set()).add(tgt)
        adjacency.setdefault(tgt, set()).add(src)

    # Friends with interactions but no mutual connections might be hidden
    for user_id, node in nodes.items():
        if node.type == "friend" and node.meet_count > 0:
            if user_id not in adjacency or len(adjacency.get(user_id, set())) == 0:
                node.is_hidden_friend = True


def _calculate_metrics(
    nodes: Dict[str, NodeData], now: _dt.datetime, halflife_days: int
) -> None:
    """Calculate relationship strength, recent intimacy, and other metrics."""
    now_ts = now.timestamp()
    decay_lambda = math.log(2) / (halflife_days * 86400)  # per second

    # Calculate per-user lifespan for life_share
    total_days = 0
    for node in nodes.values():
        if node._first_met:
            days = (now - node._first_met).total_seconds() / 86400
            node.days_known = int(days)
            total_days = max(total_days, days)

    # Find max values for normalization
    max_play_time = max((n.play_time for n in nodes.values()), default=1) or 1
    max_meet_count = max((n.meet_count for n in nodes.values()), default=1) or 1

    for node in nodes.values():
        if node.play_time <= 0:
            continue

        # === Relationship Strength (long-term) ===
        # Depth score (40%): log-scaled total time with decay
        decayed_time = 0.0
        for ts, duration in node._sessions:
            age = now_ts - ts.timestamp()
            weight = math.exp(-decay_lambda * age)
            decayed_time += duration * weight

        # Normalize and apply log scale
        depth_raw = math.log1p(decayed_time / 3600) / math.log1p(max_play_time / 3600)
        depth_score = min(40, depth_raw * 40)

        # Quality score (25%): retention rate (effective time / total time)
        # Approximate effective time as sessions with reasonable duration (< 4 hours)
        effective_time = sum(min(d, 4 * 3600) for _, d in node._sessions)
        node.effective_hours = effective_time
        node.retention_rate = (
            effective_time / node.play_time if node.play_time > 0 else 0
        )
        quality_score = min(25, node.retention_rate * 25)

        # Stability score (20%): based on days known and regularity
        stability_raw = min(1, node.days_known / 365)  # Cap at 1 year
        stability_score = stability_raw * 20

        # Bond score (15%): frequency of meetings
        freq_raw = math.log1p(node.meet_count) / math.log1p(max_meet_count)
        bond_score = min(15, freq_raw * 15)

        node.relationship_strength = (
            depth_score + quality_score + stability_score + bond_score
        )

        # === Recent Intimacy (short-term) ===
        # Calculate for different time windows
        for window_days, attr_name in [
            (30, "recent_intimacy_30d"),
            (60, "recent_intimacy_60d"),
            (90, "recent_intimacy_90d"),
        ]:
            window_start = now_ts - window_days * 86400
            recent_time = 0.0
            recent_count = 0
            for ts, duration in node._sessions:
                if ts.timestamp() >= window_start:
                    recent_time += duration
                    recent_count += 1

            # Time score (40%): recent play time
            time_score = min(40, (recent_time / 3600) / 10 * 40)  # 10 hours = max

            # Frequency score (30%): recent meet count
            freq_score = min(30, recent_count / 20 * 30)  # 20 meetings = max

            # Life share score (30%): percentage of recent life spent together
            window_hours = window_days * 24
            life_share = (recent_time / 3600) / window_hours if window_hours > 0 else 0
            share_score = min(30, life_share * 100 * 30)  # 1% = max

            intimacy = time_score + freq_score + share_score
            setattr(node, attr_name, intimacy)

            if window_days == 30:
                node.life_share = life_share

        # Default recent_intimacy is 30d
        node.recent_intimacy = node.recent_intimacy_30d


def _build_gexf(
    nodes: Dict[str, NodeData],
    edges: Sequence[Tuple[str, str]],
    friend_info: Dict[str, Tuple[str, str]],
) -> str:
    """Build GEXF XML string with all attributes."""
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
        if node_id in EXCLUDED_IDS:
            continue
        node = nodes[node_id]

        # Get display name and trust level from friend_info
        display_name, trust_level = friend_info.get(node_id, ("", ""))
        if not display_name:
            display_name = node.display_name
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

    for index, (source, target) in enumerate(edges):
        lines.append(
            f'      <edge id="{index}" source={quoteattr(source)} target={quoteattr(target)} />'
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

        # Load basic data
        friend_ids = _load_friend_ids(conn, prefix)
        edges = _load_edges(conn, prefix)
        friend_info = _load_friend_info(conn, prefix)

        # Get database "now" time
        now = _get_db_max_time(conn)
        print(f"Database time reference: {now.isoformat()}")

        # Load play data and create nodes
        nodes = _load_play_data(conn, friend_ids, now)

        # Add mutual-only nodes from edges
        for _, mutual_id in edges:
            if mutual_id and mutual_id not in nodes and mutual_id not in EXCLUDED_IDS:
                nodes[mutual_id] = NodeData(mutual_id)
                nodes[mutual_id].type = "mutual"

        # Detect hidden friends
        _detect_hidden_friends(conn, prefix, nodes, edges)

    finally:
        conn.close()

    # Calculate metrics
    _calculate_metrics(nodes, now, args.halflife)

    # Build GEXF
    gexf_text = _build_gexf(nodes, edges, friend_info)

    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(gexf_text, encoding="utf-8")

    # Statistics
    friend_count = sum(1 for n in nodes.values() if n.type == "friend")
    mutual_count = sum(1 for n in nodes.values() if n.type == "mutual")
    hidden_count = sum(1 for n in nodes.values() if n.is_hidden_friend)

    print(
        f"Exported {len(nodes)} nodes ({friend_count} friends, {mutual_count} mutuals) "
        f"and {len(edges)} edges to {output_path}"
    )
    if hidden_count > 0:
        print(f"Detected {hidden_count} potential hidden friends")


if __name__ == "__main__":
    try:
        main()
    except ExportError as exc:
        raise SystemExit(f"error: {exc}") from exc
