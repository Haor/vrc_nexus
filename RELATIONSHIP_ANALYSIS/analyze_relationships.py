#!/usr/bin/env python3
"""
VRC Nexus 关系分析工具 V2.1 - 带遗忘机制
=======================================
支持"有效时长"计算，近期互动比历史互动保留更多。

使用方法：
    python analyze_relationships.py --db VRCX.sqlite3
    python analyze_relationships.py --db VRCX.sqlite3 --halflife 180
    python analyze_relationships.py --db VRCX.sqlite3 --halflife auto --recent auto
    python analyze_relationships.py --db VRCX.sqlite3 -r
    python analyze_relationships.py --db VRCX.sqlite3 -r usr
    
半衰期选项 (--halflife)：
    60     短期记忆，强调近期互动
    120    中期记忆
    180    长期记忆，更看重历史
    365    几乎不衰减
    auto   自适应：90 × (2 - 活跃度)，范围90-180天

近期窗口选项 (--recent)：
    30     固定30天窗口
    45     固定45天窗口
    60     固定60天窗口
    auto   自适应：30 + (1 - 活跃度) × 30，范围30-60天

导出选项：
    -r, --export-rankings           导出两个排名CSV文件
    -r usr, --export-rankings usr   导出带前缀的排名CSV文件
"""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path
from datetime import datetime
from typing import Dict, Set, Tuple, Optional
import sys

try:
    import pandas as pd
    import numpy as np
except ImportError:
    print("错误：需要安装 pandas 和 numpy")
    print("运行：pip install pandas numpy")
    sys.exit(1)

EXCLUDED_IDS = {"usr_00000000-0000-0000-0000-000000000000"}


class AnalysisError(RuntimeError):
    """分析错误"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="分析 VRCX 好友关系（带遗忘机制版本）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
参数说明：
  --halflife: 半衰期（历史互动的"遗忘速度"）
    auto   根据活跃度自动计算：90×(2-活跃度)，范围90-180天
    60-365 手动指定天数
    
  --recent: 近期窗口（计算"近期亲密度"的时间范围）
    auto   根据活跃度自动计算：30+(1-活跃度)×30，范围30-60天
    30-60  手动指定天数
"""
    )
    parser.add_argument("--db", default="VRCX.sqlite3", help="数据库路径")
    parser.add_argument("--win", action="store_true", help="使用 Windows 默认路径")
    parser.add_argument("--output", "-o", default="relationship_report.md", help="输出报告")
    parser.add_argument("--export-rankings", "-r", nargs='?', const='', default=None, 
                        help="导出两个排名CSV，可选前缀，如：-r usr")
    parser.add_argument("--top", "-n", type=int, default=25, help="显示前 N 名")
    parser.add_argument("--prefix", help="数据表前缀")
    parser.add_argument(
        "--halflife",
        default="auto",
        help="半衰期天数，或 'auto' 自适应 (默认: auto)"
    )
    parser.add_argument(
        "--recent",
        default="auto",
        help="近期窗口天数，或 'auto' 自适应 (默认: auto)"
    )
    return parser.parse_args()


def resolve_db_path(args: argparse.Namespace) -> Path:
    if args.win:
        appdata = os.environ.get("APPDATA")
        if not appdata:
            raise AnalysisError("APPDATA 环境变量未设置")
        path = Path(appdata) / "VRCX" / "VRCX.sqlite3"
        if not path.exists():
            raise AnalysisError(f"数据库不存在: {path}")
        return path
    return Path(args.db).expanduser()


def detect_prefix(conn: sqlite3.Connection, explicit_prefix: Optional[str]) -> str:
    if explicit_prefix:
        for suffix in ("_friend_log_current", "_mutual_graph_links"):
            if explicit_prefix.endswith(suffix):
                return explicit_prefix[:-len(suffix)]
        return explicit_prefix
    
    cursor = conn.cursor()
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%_friend_log_current'")
    rows = cursor.fetchall()
    
    prefixes = [name[:-len("_friend_log_current")] for (name,) in rows if name.endswith("_friend_log_current")]
    
    if not prefixes:
        raise AnalysisError("未找到好友数据表")
    if len(prefixes) > 1:
        raise AnalysisError(f"发现多个用户，请用 --prefix 指定: {', '.join(prefixes)}")
    return prefixes[0]


def get_self_user_id(prefix: str) -> str:
    if prefix.startswith("usr"):
        raw = prefix[3:]
        if len(raw) == 32:
            return f"usr_{raw[:8]}-{raw[8:12]}-{raw[12:16]}-{raw[16:20]}-{raw[20:]}"
    return ""


class RelationshipAnalyzerV2:
    def __init__(self, conn: sqlite3.Connection, prefix: str, halflife: str, recent: str = "auto"):
        self.conn = conn
        self.prefix = prefix
        self.self_user_id = get_self_user_id(prefix)
        self.halflife_setting = halflife
        self.recent_setting = recent
        self.halflife: float = 120.0
        self.recent_window: int = 30
        self.activity_factor: float = 0.5
        self.max_date: Optional[datetime] = None
        self.total_days: int = 0
        self.friend_ids: Set[str] = set()
        self.friend_names: Dict[str, str] = {}
    
    def load_friend_list(self) -> int:
        query = f"SELECT user_id, display_name FROM {self.prefix}_friend_log_current"
        df = pd.read_sql_query(query, self.conn)
        self.friend_ids = set(df['user_id'].tolist())
        self.friend_names = dict(zip(df['user_id'], df['display_name']))
        return len(self.friend_ids)
    
    def get_date_range(self) -> Tuple[datetime, int]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT MAX(date(created_at)), MIN(date(created_at)) FROM gamelog_join_leave")
        max_str, min_str = cursor.fetchone()
        self.max_date = datetime.strptime(max_str, '%Y-%m-%d')
        min_date = datetime.strptime(min_str, '%Y-%m-%d')
        self.total_days = (self.max_date - min_date).days + 1
        return self.max_date, self.total_days
    
    def set_adaptive_params(self) -> dict:
        """设置半衰期和近期窗口（支持 auto 或手动指定）"""
        result = {}
        
        # 先计算活跃度因子（两个参数都可能需要）
        cursor = self.conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT date(created_at)) FROM gamelog_location")
        my_active_days = cursor.fetchone()[0]
        self.activity_factor = min(my_active_days / self.total_days, 1.0)
        result['my_active_days'] = my_active_days
        result['total_days'] = self.total_days
        result['activity_factor'] = self.activity_factor
        
        # 设置半衰期
        if self.halflife_setting == 'auto':
            self.halflife = 90 * (2 - self.activity_factor)
            result['halflife_mode'] = 'auto'
        else:
            try:
                self.halflife = float(self.halflife_setting)
                result['halflife_mode'] = 'manual'
            except ValueError:
                raise AnalysisError(f"无效的半衰期设置: {self.halflife_setting}")
        result['final_halflife'] = self.halflife
        
        # 设置近期窗口
        if self.recent_setting == 'auto':
            self.recent_window = int(30 + (1 - self.activity_factor) * 30)
            result['recent_mode'] = 'auto'
        else:
            try:
                self.recent_window = int(self.recent_setting)
                result['recent_mode'] = 'manual'
            except ValueError:
                raise AnalysisError(f"无效的近期窗口设置: {self.recent_setting}")
        result['recent_window'] = self.recent_window
        
        return result
    
    def get_daily_interactions(self) -> pd.DataFrame:
        query = """
        SELECT user_id, date(created_at) as day, SUM(CASE WHEN time > 0 THEN time ELSE 0 END) / 3600000.0 as hours
        FROM gamelog_join_leave
        WHERE type = 'OnPlayerLeft'
        GROUP BY user_id, date(created_at)
        """
        df = pd.read_sql_query(query, self.conn)
        df = df[df['user_id'].isin(self.friend_ids)]
        if self.self_user_id:
            df = df[df['user_id'] != self.self_user_id]
        df['name'] = df['user_id'].map(self.friend_names)
        df['day'] = pd.to_datetime(df['day'])
        return df
    
    def calculate_effective_hours(self, daily_df: pd.DataFrame) -> pd.DataFrame:
        """计算有效时长（带衰减）
        
        重要：使用 user_id 作为主键，避免同名好友数据被覆盖
        """
        results = []
        
        for user_id in daily_df['user_id'].unique():
            friend_data = daily_df[daily_df['user_id'] == user_id]
            
            effective = 0.0
            total = 0.0
            
            for _, row in friend_data.iterrows():
                days_ago = (self.max_date - row['day']).days
                weight = 2 ** (-days_ago / self.halflife)
                effective += row['hours'] * weight
                total += row['hours']
            
            results.append({
                'user_id': user_id,
                'total_hours': total,
                'effective_hours': effective,
                'retention_rate': effective / total if total > 0 else 0
            })
        
        return pd.DataFrame(results)
    
    def get_friend_stats(self) -> pd.DataFrame:
        query = """
        SELECT user_id, 
               COUNT(*) as interaction_count,
               COUNT(DISTINCT location) as meet_count,
               COUNT(DISTINCT date(created_at)) as active_days
        FROM gamelog_join_leave 
        WHERE type = 'OnPlayerLeft' AND time > 0
        GROUP BY user_id
        """
        df = pd.read_sql_query(query, self.conn)
        df = df[df['user_id'].isin(self.friend_ids)]
        if self.self_user_id:
            df = df[df['user_id'] != self.self_user_id]
        df['name'] = df['user_id'].map(self.friend_names)
        return df
    
    def get_recent_stats(self) -> pd.DataFrame:
        query = f"""
        SELECT user_id, 
               SUM(time) / 3600000.0 as recent_hours, 
               COUNT(DISTINCT location) as recent_meets
        FROM gamelog_join_leave 
        WHERE type = 'OnPlayerLeft' AND time > 0
            AND created_at >= datetime((SELECT MAX(date(created_at)) FROM gamelog_join_leave), '-{self.recent_window} days')
        GROUP BY user_id
        """
        df = pd.read_sql_query(query, self.conn)
        df = df[df['user_id'].isin(self.friend_ids)]
        return df
    
    def get_mutual_friends(self) -> pd.DataFrame:
        query = f"SELECT friend_id as user_id, COUNT(*) as connections FROM {self.prefix}_mutual_graph_links GROUP BY friend_id"
        df = pd.read_sql_query(query, self.conn)
        df = df[df['user_id'].isin(self.friend_ids)]
        return df
    
    def get_my_recent_hours(self) -> float:
        query = f"""
        SELECT SUM(time) / 3600000.0
        FROM gamelog_location
        WHERE created_at >= datetime((SELECT MAX(date(created_at)) FROM gamelog_location), '-{self.recent_window} days')
        """
        cursor = self.conn.cursor()
        cursor.execute(query)
        result = cursor.fetchone()[0]
        return result if result else 0
    
    def calculate_relationship_strength(self, df: pd.DataFrame) -> pd.DataFrame:
        """关系强度 V2 - 使用有效时长，含隐藏好友检测"""
        result = df.copy()
        
        # 有效陪伴深度 (40%)
        result['depth_percentile'] = result['effective_hours'].rank(pct=True)
        result['depth_score'] = result['depth_percentile'] * 40
        
        # 互动质量 (25%) - 使用 interaction_count 计算平均每次互动时长
        result['avg_duration'] = result['total_hours'] / result['interaction_count']
        median_duration = result['avg_duration'].median()
        result['quality_score'] = (result['avg_duration'] / (result['avg_duration'] + median_duration)) * 25
        
        # 稳定性 (20%)
        result['stability_ratio'] = result['active_days'] / self.total_days
        result['stability_score'] = np.sqrt(result['stability_ratio']) * 20
        
        # 社交羁绊 (15%) - 含隐藏好友动态识别
        result['is_hidden_friend'] = False
        result['bond_score'] = 7.5
        
        if 'connections' in result.columns:
            # 正常好友
            has_connections = result['connections'] > 0
            if has_connections.any():
                result.loc[has_connections, 'bond_percentile'] = result.loc[has_connections, 'connections'].rank(pct=True)
                result.loc[has_connections, 'bond_score'] = result.loc[has_connections, 'bond_percentile'] * 15
            
            # 隐藏好友检测（使用总时长，不受衰减影响）
            zero_conn = result['connections'] == 0
            hours_p70 = result['total_hours'].quantile(0.70)
            meets_p70 = result['meet_count'].quantile(0.70)
            high_interaction = (result['total_hours'] > hours_p70) | (result['meet_count'] > meets_p70)
            hidden = zero_conn & high_interaction
            
            result.loc[hidden, 'is_hidden_friend'] = True
            result.loc[hidden, 'bond_score'] = result.loc[hidden, 'depth_percentile'] * 15
        
        result['relationship_strength'] = (
            result['depth_score'] + result['quality_score'] + 
            result['stability_score'] + result['bond_score']
        )
        return result
    
    def calculate_recent_intimacy(self, df: pd.DataFrame, my_recent_hours: float) -> pd.DataFrame:
        result = df.copy()
        result['recent_hours'] = result['recent_hours'].fillna(0)
        result['recent_meets'] = result['recent_meets'].fillna(0)
        
        has_recent = result['recent_hours'] > 0
        
        result['recent_time_score'] = 0.0
        if has_recent.any():
            result.loc[has_recent, 'recent_time_score'] = result.loc[has_recent, 'recent_hours'].rank(pct=True) * 40
        
        result['recent_freq_score'] = 0.0
        if has_recent.any():
            result.loc[has_recent, 'recent_freq_score'] = result.loc[has_recent, 'recent_meets'].rank(pct=True) * 30
        
        result['life_share'] = 0.0
        result['share_score'] = 0.0
        if my_recent_hours > 0:
            result['life_share'] = result['recent_hours'] / my_recent_hours
            share_median = result.loc[has_recent, 'life_share'].median() if has_recent.any() else 0.01
            result['share_score'] = (result['life_share'] / (result['life_share'] + max(share_median, 0.01))) * 30
        
        result['recent_intimacy'] = result['recent_time_score'] + result['recent_freq_score'] + result['share_score']
        return result
    
    def analyze(self) -> Tuple[pd.DataFrame, dict]:
        print("加载好友列表...")
        friend_count = self.load_friend_list()
        print(f"  好友数量: {friend_count}")
        
        print("获取数据范围...")
        max_date, total_days = self.get_date_range()
        print(f"  数据范围: {total_days} 天，截至 {max_date.strftime('%Y-%m-%d')}")
        
        print("计算半衰期和近期窗口...")
        params_info = self.set_adaptive_params()
        
        # 显示活跃度信息（如果有任一个是 auto）
        if self.halflife_setting == 'auto' or self.recent_setting == 'auto':
            print(f"  我的活跃天数: {params_info['my_active_days']} / {params_info['total_days']} 天")
            print(f"  活跃度因子: {params_info['activity_factor']:.2f}")
        
        # 显示半衰期
        if params_info.get('halflife_mode') == 'auto':
            print(f"  半衰期: 90 × (2 - {params_info['activity_factor']:.2f}) = {self.halflife:.0f} 天 [auto]")
        else:
            print(f"  半衰期: {self.halflife:.0f} 天 [手动指定]")
        
        # 显示近期窗口
        if params_info.get('recent_mode') == 'auto':
            print(f"  近期窗口: 30 + (1 - {params_info['activity_factor']:.2f}) × 30 = {self.recent_window} 天 [auto]")
        else:
            print(f"  近期窗口: {self.recent_window} 天 [手动指定]")
        
        print(f"  >>> 半衰期: {self.halflife:.0f} 天 | 近期窗口: {self.recent_window} 天 <<<")
        print(f"  含义: {self.halflife:.0f}天前的1小时 = 现在的0.5小时")
        
        print("获取互动数据...")
        daily_df = self.get_daily_interactions()
        friend_stats = self.get_friend_stats()
        recent_stats = self.get_recent_stats()
        mutual_friends = self.get_mutual_friends()
        my_recent_hours = self.get_my_recent_hours()
        
        print("计算有效时长...")
        effective_df = self.calculate_effective_hours(daily_df)
        print(f"  有互动记录的好友: {len(effective_df)}")
        print(f"  我近{self.recent_window}天在线: {my_recent_hours:.1f} 小时")
        
        # 合并（全部使用 user_id 作为主键，避免同名好友问题）
        df = friend_stats.merge(effective_df, on='user_id', how='inner')
        df = df.merge(recent_stats, on='user_id', how='left')
        df = df.merge(mutual_friends, on='user_id', how='left')
        df['connections'] = df['connections'].fillna(0)
        
        print("计算关系强度 V2...")
        df = self.calculate_relationship_strength(df)
        
        print("计算近期亲密度...")
        df = self.calculate_recent_intimacy(df, my_recent_hours)
        
        params_info['recent_window'] = self.recent_window
        return df, params_info


def generate_report(df: pd.DataFrame, total_days: int, halflife: float, halflife_info: dict, top_n: int) -> str:
    recent_window = halflife_info.get('recent_window', 30)
    lines = []
    lines.append("=" * 70)
    lines.append("VRC Nexus 关系分析报告 V2.1 - 带遗忘机制")
    lines.append("=" * 70)
    lines.append(f"\n数据范围：{total_days} 天")
    lines.append(f"好友总数：{len(df)} 人")
    lines.append(f"半衰期：{halflife:.0f} 天 | 近期窗口：{recent_window} 天")
    lines.append(f"报告时间：{datetime.now().strftime('%Y-%m-%d %H:%M')}")
    
    # 关系强度排名
    df_strength = df.sort_values('relationship_strength', ascending=False).head(top_n)
    lines.append("\n" + "=" * 70)
    lines.append("【关系强度排名 V2】- 使用有效时长（带遗忘）")
    lines.append("=" * 70)
    lines.append(f"\n{'排名':<4} {'好友':<18} {'总时长':<8} {'有效时长':<8} {'保留率':<8} {'强度%':<6} {'标记':<6}")
    lines.append("-" * 75)
    
    for i, row in enumerate(df_strength.itertuples(), 1):
        retention = row.retention_rate * 100
        mark = "隐藏" if (hasattr(row, 'is_hidden_friend') and row.is_hidden_friend) else ""
        lines.append(
            f"{i:<4} {row.name:<18} {row.total_hours:>6.1f}h  {row.effective_hours:>6.1f}h  "
            f"{retention:>5.1f}%   {row.relationship_strength:>5.1f}%  {mark}"
        )
    
    # 近期亲密度排名
    df_recent = df.sort_values('recent_intimacy', ascending=False).head(top_n)
    lines.append("\n" + "=" * 70)
    lines.append(f"【近期亲密度排名】- 近 {recent_window} 天")
    lines.append("=" * 70)
    lines.append(f"\n{'排名':<4} {'好友':<18} {'近期h':<8} {'见面次':<6} {'生命份额':<10} {'亲密度':<6}")
    lines.append("-" * 70)
    
    for i, row in enumerate(df_recent.itertuples(), 1):
        share_pct = row.life_share * 100 if pd.notna(row.life_share) else 0
        recent_hours = row.recent_hours if pd.notna(row.recent_hours) else 0
        recent_meets = int(row.recent_meets) if pd.notna(row.recent_meets) else 0
        lines.append(
            f"{i:<4} {row.name:<18} {recent_hours:>6.1f}h  {recent_meets:>4}次   "
            f"{share_pct:>6.2f}%     {row.recent_intimacy:>5.1f}"
        )
    
    # 隐藏好友检测
    if 'is_hidden_friend' in df.columns:
        hidden = df[df['is_hidden_friend'] == True].sort_values('total_hours', ascending=False)
        if len(hidden) > 0:
            lines.append(f"\n🔒 检测到的隐藏好友（共同好友=0 但互动量高）：")
            for row in hidden.itertuples():
                lines.append(f"   - {row.name}: {row.total_hours:.1f}h, {row.meet_count}次见面")
    
    # 保留率分析
    lines.append("\n" + "=" * 70)
    lines.append("【有效时长分析】- 遗忘机制的影响")
    lines.append("=" * 70)
    
    # 保留率最低
    low_retention = df[df['total_hours'] > 30].nsmallest(8, 'retention_rate')
    lines.append("\n📉 保留率最低（关系正在淡化）：")
    for row in low_retention.itertuples():
        lines.append(f"   - {row.name}: 总{row.total_hours:.0f}h → 有效{row.effective_hours:.1f}h (保留{row.retention_rate*100:.1f}%)")
    
    # 保留率最高
    high_retention = df[df['total_hours'] > 20].nlargest(8, 'retention_rate')
    lines.append("\n📈 保留率最高（关系很新鲜）：")
    for row in high_retention.itertuples():
        lines.append(f"   - {row.name}: 总{row.total_hours:.0f}h → 有效{row.effective_hours:.1f}h (保留{row.retention_rate*100:.1f}%)")
    
    return "\n".join(lines)


def main():
    args = parse_args()
    db_path = resolve_db_path(args)
    if not db_path.exists():
        raise AnalysisError(f"数据库不存在: {db_path}")
    
    print(f"数据库: {db_path}")
    
    conn = sqlite3.connect(db_path)
    try:
        prefix = detect_prefix(conn, args.prefix)
        print(f"用户前缀: {prefix}")
        
        analyzer = RelationshipAnalyzerV2(conn, prefix, args.halflife, args.recent)
        df, params_info = analyzer.analyze()
        
        report = generate_report(df, analyzer.total_days, analyzer.halflife, params_info, args.top)
        print("\n" + report)
        
        Path(args.output).write_text(report, encoding='utf-8')
        print(f"\n报告已保存到: {args.output}")
        
        # 导出排名CSV
        if args.export_rankings is not None:
            cols = ['name', 'total_hours', 'effective_hours', 'retention_rate', 
                    'meet_count', 'interaction_count', 'active_days', 'connections', 
                    'recent_hours', 'recent_meets', 'relationship_strength', 'recent_intimacy']
            
            # 生成文件名（带可选前缀）
            prefix = f"{args.export_rankings}_" if args.export_rankings else ""
            
            # 关系强度排名
            strength_file = f'{prefix}relationship_strength_ranking.csv'
            df_strength = df.sort_values('relationship_strength', ascending=False).copy()
            df_strength.insert(0, 'rank', range(1, len(df_strength) + 1))
            df_strength[[c for c in ['rank'] + cols if c in df_strength.columns]].to_csv(strength_file, index=False)
            print(f"关系强度排名已保存到: {strength_file}")
            
            # 近期亲密度排名
            intimacy_file = f'{prefix}recent_intimacy_ranking.csv'
            df_intimacy = df.sort_values('recent_intimacy', ascending=False).copy()
            df_intimacy.insert(0, 'rank', range(1, len(df_intimacy) + 1))
            df_intimacy[[c for c in ['rank'] + cols if c in df_intimacy.columns]].to_csv(intimacy_file, index=False)
            print(f"近期亲密度排名已保存到: {intimacy_file}")
    finally:
        conn.close()


if __name__ == "__main__":
    try:
        main()
    except AnalysisError as e:
        print(f"错误: {e}", file=sys.stderr)
        sys.exit(1)
