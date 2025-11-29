#!/usr/bin/env python3
"""
Export the cached VRCX mutual friend network into a GEXF graph file.
Windows 默认数据库路径：%APPDATA%\\VRCX\\VRCX.sqlite3
注意：依托 VRCX 本地数据库，需使用 VRCX nightly 并手动在客户端执行 Fetch Mutual Friends 后再导出。
"""

from __future__ import annotations

import argparse
import datetime as _dt
import os
import sqlite3
from pathlib import Path
from typing import Dict, Iterable, List, Sequence, Tuple
from xml.sax.saxutils import quoteattr

# IDs that should be excluded from export (e.g. placeholder/hidden mutuals)
EXCLUDED_IDS = {"usr_00000000-0000-0000-0000-000000000000"}


class ExportError(RuntimeError):
    """Raised when the exporter cannot proceed."""


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
    return parser.parse_args()


def _quote_table_name(name: str) -> str:
    if not name or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_" for c in name):
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
        raise ExportError("Could not find any *_mutual_graph_links tables in the database.")
    if len(unique_matches) > 1:
        raise ExportError(
            "Multiple mutual graph datasets found. Please specify one with --prefix. "
            f"Detected prefixes: {', '.join(unique_matches)}"
        )
    return unique_matches[0]


def _load_display_names(conn: sqlite3.Connection, prefix: str) -> Dict[str, str]:
    table = _quote_table_name(f"{prefix}_friend_log_current")
    rows = conn.execute(f"SELECT user_id, display_name FROM {table}").fetchall()
    display_names: Dict[str, str] = {}
    for user_id, display_name in rows:
        if not user_id:
            continue
        if display_name:
            display_names[user_id] = display_name
    return display_names


def _resolve_db_path(args: argparse.Namespace) -> Path:
    if args.win:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise ExportError("APPDATA is not set; cannot resolve Windows default DB path.")
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


def _attribute_block(nodes: Iterable[Tuple[str, str, str, str]]) -> List[str]:
    lines: List[str] = [
        "    <attributes class=\"node\" mode=\"static\">",
        "      <attribute id=\"0\" title=\"type\" type=\"string\"/>",
        "      <attribute id=\"1\" title=\"displayName\" type=\"string\"/>",
        "    </attributes>",
        "    <nodes>",
    ]
    for node_id, node_type, label, display_name in nodes:
        attr_id = f"id={quoteattr(node_id)}"
        attr_label = f"label={quoteattr(label or node_id)}"
        lines.append(f"      <node {attr_id} {attr_label}>")
        lines.append("        <attvalues>")
        lines.append(f"          <attvalue for=\"0\" value={quoteattr(node_type)} />")
        att_value = display_name if display_name else label or node_id
        lines.append(f"          <attvalue for=\"1\" value={quoteattr(att_value)} />")
        lines.append("        </attvalues>")
        lines.append("      </node>")
    lines.append("    </nodes>")
    return lines


def _edge_block(edges: Sequence[Tuple[str, str]]) -> List[str]:
    lines = ["    <edges>"]
    for index, (source, target) in enumerate(edges):
        attr_id = f"id=\"{index}\""
        attr_source = f"source={quoteattr(source)}"
        attr_target = f"target={quoteattr(target)}"
        lines.append(f"      <edge {attr_id} {attr_source} {attr_target} />")
    lines.append("    </edges>")
    return lines


def _build_gexf(nodes: Iterable[Tuple[str, str, str, str]], edges: Sequence[Tuple[str, str]]) -> str:
    timestamp = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
    lines: List[str] = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<gexf xmlns="http://www.gexf.net/1.3draft" version="1.3">',
        f"  <meta lastmodifieddate=\"{timestamp}\">",
        "    <creator>VRCX Mutual Graph Exporter</creator>",
        "    <description>Mutual friend network exported from VRCX</description>",
        "  </meta>",
        '  <graph mode="static" defaultedgetype="undirected">',
    ]
    lines.extend(_attribute_block(nodes))
    lines.extend(_edge_block(edges))
    lines.append("  </graph>")
    lines.append("</gexf>")
    return "\n".join(lines)


def _prepare_nodes(
    friend_ids: Sequence[str],
    edges: Sequence[Tuple[str, str]],
    display_names: Dict[str, str],
) -> List[Tuple[str, str, str, str]]:
    friend_set = set(friend_ids)
    node_ids = set(friend_ids)
    for _, mutual_id in edges:
        if mutual_id:
            node_ids.add(mutual_id)
    nodes: List[Tuple[str, str, str, str]] = []
    for node_id in sorted(node_ids):
        if node_id in EXCLUDED_IDS:
            continue
        node_type = "friend" if node_id in friend_set else "mutual"
        display_name = display_names.get(node_id, "")
        label = display_name or node_id
        nodes.append((node_id, node_type, label, display_name))
    return nodes


def main() -> None:
    args = _parse_args()
    db_path = _resolve_db_path(args)
    if not db_path.exists():
        raise ExportError(f"Database file not found: {db_path}")

    conn = sqlite3.connect(db_path)
    try:
        prefix = _detect_prefix(conn, args.prefix)
        display_names = _load_display_names(conn, prefix)
        friend_ids = _load_friend_ids(conn, prefix)
        edges = _load_edges(conn, prefix)
    finally:
        conn.close()

    nodes = _prepare_nodes(friend_ids, edges, display_names)
    gexf_text = _build_gexf(nodes, edges)

    output_path = Path(args.output).expanduser()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(gexf_text, encoding="utf-8")

    print(
        f"Exported {len(nodes)} nodes and {len(edges)} edges from prefix '{prefix}' to {output_path}"
    )


if __name__ == "__main__":
    try:
        main()
    except ExportError as exc:
        raise SystemExit(f"error: {exc}") from exc
