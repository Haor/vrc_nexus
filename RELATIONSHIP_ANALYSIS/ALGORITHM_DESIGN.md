# 关系分析算法设计

> 版本: 2.2
> 更新: 2025-01-29

---

## 1. 双指标体系

单一"亲密度"无法同时表达长期深度和近期热度，拆分为两个独立指标：

| 指标 | 含义 | 时间范围 | 分值 |
|------|------|----------|------|
| 关系强度 | 长期累积的关系深度 | 全历史（带衰减） | 0-100 |
| 近期亲密度 | 近期互动热度 | 自适应窗口（30-60天） | 0-100 |

---

## 2. 时间衰减

### 2.1 有效时长

```
有效时长 = Σ(当日时长 × 2^(-天数差/半衰期))
```

- 今天的 1 小时 = 1.0 小时有效
- 半衰期天前的 1 小时 = 0.5 小时有效
- 2 个半衰期前的 1 小时 = 0.25 小时有效

### 2.2 自适应半衰期

```
半衰期 = 90 × (2 - 活跃度因子)
活跃度因子 = 用户活跃天数 / 总观察天数
```

| 活跃度 | 半衰期 |
|--------|--------|
| 1.0 | 90 天 |
| 0.5 | 135 天 |
| 0.0 | 180 天 |

活跃用户经常在线却不见某好友，感知更敏锐，半衰期短。不活跃用户本就少上线，半衰期长。

### 2.3 自适应近期窗口

```
近期窗口 = 30 + (1 - 活跃度因子) × 30
```

| 活跃度 | 窗口 |
|--------|------|
| 1.0 | 30 天 |
| 0.5 | 45 天 |
| 0.0 | 60 天 |

---

## 3. 关系强度

四个维度，总分 100：

| 维度 | 权重 | 指标 | 归一化 |
|------|------|------|--------|
| 有效陪伴深度 | 40 | 有效时长 | Percentile Rank |
| 互动质量 | 25 | 总时长 / 互动事件数 | Sigmoid(k=中位数) |
| 稳定性 | 20 | 活跃天数 / 总天数 | sqrt(x) |
| 社交羁绊 | 15 | 共同好友数 | Percentile Rank |

### 3.1 有效陪伴深度 (40分)

```
depthScore = percentileRank(effectiveHours) × 40
```

Percentile Rank 自适应用户社交规模，无需定义"多少小时算多"。

### 3.2 互动质量 (25分)

```
avgDuration = totalHours / interactionCount
qualityScore = sigmoid(avgDuration, median) × 25
```

区分长时间深度交流和频繁打招呼。

### 3.3 稳定性 (20分)

```
stabilityScore = sqrt(activeDays / totalDays) × 20
```

sqrt 拉伸低端分布，区分度更明显。

### 3.4 社交羁绊 (15分)

```
bondScore = percentileRank(mutualFriends) × 15
```

**隐藏好友处理**：共同好友=0 但 (总时长 > P70 或 见面次数 > P70) 时，判定为隐藏好友，用有效陪伴深度排名替代。

---

## 4. 近期亲密度

三个维度，总分 100：

| 维度 | 权重 | 指标 | 归一化 |
|------|------|------|--------|
| 近期陪伴 | 40 | 近N天时长 | Percentile Rank |
| 近期频率 | 30 | 近N天见面次数 | Percentile Rank |
| 生命份额 | 30 | 近期与好友时长 / 用户近期总在线时长 | Sigmoid(k=中位数) |

N = 自适应近期窗口。

### 4.1 近期陪伴 (40分)

```
recentTimeScore = percentileRank(recentHours) × 40
```

### 4.2 近期频率 (30分)

```
recentFreqScore = percentileRank(recentMeets) × 30
```

### 4.3 生命份额 (30分)

```
lifeShare = recentHoursWithFriend / myRecentOnlineHours
shareScore = sigmoid(lifeShare, medianShare) × 30
```

用户忙碌时只上 10 小时，其中 8 小时给 A，A 获得 80% 份额。用户空闲时玩 200 小时，其中 20 小时给 B，B 只获得 10% 份额。份额反映稀缺时间的分配。

---

## 5. 多窗口近期亲密度

除自适应窗口外，额外计算三个固定窗口：

| 窗口 | 用途 |
|------|------|
| 30天 | 短期热度 |
| 60天 | 中期热度 |
| 90天 | 长期热度 |

计算方式与自适应窗口相同，但 Percentile Rank 在各窗口独立计算。

---

## 6. 保留率

```
保留率 = 有效时长 / 总时长
```

| 保留率 | 含义 |
|--------|------|
| 80-100% | 关系新鲜，近期频繁互动 |
| 50-80% | 正常维护 |
| 30-50% | 开始淡化 |
| <30% | 已淡化 |

---

## 7. 组合解读

| 关系强度 | 近期亲密度 | 解读 |
|----------|------------|------|
| 高 | 高 | 核心圈 |
| 高 | 低 | 老朋友疏远 |
| 低 | 高 | 新朋友升温 |
| 低 | 低 | 普通关系 |

---

## 8. 命令行

```bash
python analyze_relationships.py --db VRCX.sqlite3              # 默认半衰期 120 天
python analyze_relationships.py --db VRCX.sqlite3 --halflife auto  # 自适应半衰期
python analyze_relationships.py --db VRCX.sqlite3 -r           # 输出 CSV 排名
python analyze_relationships.py --win                          # Windows 默认路径
```

| 选项 | 半衰期 |
|------|--------|
| `--halflife 90` | 90 天 |
| `--halflife 120` | 120 天（默认） |
| `--halflife 180` | 180 天 |
| `--halflife auto` | 90×(2-活跃度) |

---

## 9. 算法伪代码

```python
def analyze():
    # 1. 计算自适应参数
    activity = my_active_days / total_days
    halflife = 90 * (2 - activity)
    recent_window = 30 + (1 - activity) * 30

    # 2. 计算有效时长
    for friend in friends:
        effective = sum(day.hours * 2**(-days_ago/halflife) for day in interactions)
        retention = effective / total_hours

    # 3. 关系强度
    for friend in friends:
        depth = percentile_rank(effective_hours) * 40
        quality = sigmoid(avg_duration, median) * 25
        stability = sqrt(active_days / total_days) * 20
        bond = percentile_rank(mutual_friends) * 15  # 含隐藏好友检测
        relationship_strength = depth + quality + stability + bond

    # 4. 近期亲密度
    for friend in friends:
        if recent_hours > 0:
            time_score = percentile_rank(recent_hours) * 40
            freq_score = percentile_rank(recent_meets) * 30
            share_score = sigmoid(life_share, median_share) * 30
            recent_intimacy = time_score + freq_score + share_score
        else:
            recent_intimacy = 0
```
