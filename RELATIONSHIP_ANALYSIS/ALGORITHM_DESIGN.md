# 关系分析算法设计

> 版本: 2.4 | 更新: 2025-01-30

---

## 1. 双指标体系

将"亲密度"拆分为两个独立指标：

| 指标 | 定义 | 时间范围 | 分值 |
|------|------|----------|------|
| 关系强度 | 长期累积的关系深度 | 全历史（带衰减） | 0-100 |
| 近期亲密度 | 近期互动热度 | 自适应窗口（30-60天） | 0-100 |

**设计依据**：
- 关系强度回答"我们是不是好朋友"，不因短期忙碌而骤降
- 近期亲密度回答"我们最近联系多吗"，反映当前状态

---

## 2. 时间衰减模型

### 2.1 有效时长

关系需要维护，不联系就会淡化。用指数衰减模拟这一过程：

```
有效时长 = Σ(当日时长 × 2^(-天数差/半衰期))
```

示例（半衰期=90天）：
| 时间点 | 衰减权重 | 1小时实际贡献 |
|--------|----------|---------------|
| 今天 | 1.0 | 1.0 小时 |
| 90天前 | 0.5 | 0.5 小时 |
| 180天前 | 0.25 | 0.25 小时 |

### 2.2 自适应半衰期

```
半衰期 = 90 × (2 - 活跃度因子)
活跃度因子 = 用户活跃天数 / 总观察天数
```

**参数设计**：
- 基准值 90 天：对应"3个月不联系开始明显疏远"的普遍体感
- 范围 90~180 天：活跃用户感知敏锐用短周期，不活跃用户更宽容用长周期

| 活跃度 | 半衰期 | 说明 |
|--------|--------|------|
| 1.0 | 90 天 | 每天上线 |
| 0.5 | 135 天 | 半数天数上线 |
| 0.0 | 180 天 | 几乎不上线 |

**计算示例**：

```
用户A: 活跃天数 543/626 = 0.87 → 半衰期 = 90 × 1.13 = 102天
用户B: 活跃天数 100/500 = 0.20 → 半衰期 = 90 × 1.80 = 162天
```

### 2.3 自适应近期窗口

```
近期窗口 = 30 + (1 - 活跃度因子) × 30
```

| 活跃度 | 窗口 |
|--------|------|
| 1.0 | 30 天 |
| 0.5 | 45 天 |
| 0.0 | 60 天 |

设计与半衰期对称：活跃度低则窗口更长，避免不活跃用户的近期亲密度大量为零。

---

## 3. 关系强度

四个维度加权求和，总分 100：

| 维度 | 权重 | 指标 | 归一化方法 |
|------|------|------|------------|
| 有效陪伴深度 | 40 | 有效时长 | Percentile Rank |
| 互动质量 | 25 | 平均每次互动时长 | Sigmoid |
| 稳定性 | 20 | 活跃天数占比 | sqrt |
| 社交羁绊 | 15 | 共同好友数 | Percentile Rank |

### 3.1 有效陪伴深度 (40分)

```
depthScore = percentileRank(effectiveHours) × 40
```

采用 Percentile Rank 的原因：自适应用户社交规模。100小时对社交活跃者可能只排50%，对独居者可能排95%。

### 3.2 互动质量 (25分)

```
avgDuration = totalHours / interactionCount
qualityScore = sigmoid(avgDuration, median) × 25
```

- `interactionCount`：进出房间事件总数
- `median`：所有好友的中位数

采用 Sigmoid 的原因：提供平滑饱和曲线，k=中位数意味着超过一半人即可获得一半分数。

### 3.3 稳定性 (20分)

```
stabilityScore = sqrt(activeDays / totalDays) × 20
```

采用 sqrt 的原因：原始比例分布偏态（多数人比例低），开方拉伸低端增加区分度。

### 3.4 社交羁绊 (15分)

```
bondScore = percentileRank(mutualFriends) × 15
```

**隐藏好友处理**：

部分用户隐藏好友列表导致共同好友=0，需特殊处理：

| 条件 | 处理方式 |
|------|----------|
| 共同好友 > 0 | 按共同好友数排名 |
| 共同好友 = 0 且 (时长 > P70 或 见面次数 > P70) | 判定为隐藏好友，用有效陪伴深度排名替代 |
| 共同好友 = 0 且 互动量低 | 给中等分 (50%) |

---

## 4. 近期亲密度

三个维度加权求和，总分 100：

| 维度 | 权重 | 指标 | 归一化方法 |
|------|------|------|------------|
| 近期陪伴 | 40 | 近N天时长 | Percentile Rank |
| 近期频率 | 30 | 近N天见面次数 | Percentile Rank |
| 生命份额 | 30 | 好友时长 / 用户总在线时长 | Sigmoid |

N = 自适应近期窗口

### 4.1 近期陪伴 (40分)

```
recentTimeScore = percentileRank(recentHours) × 40
```

仅在有近期互动的好友中排名。

### 4.2 近期频率 (30分)

```
recentFreqScore = percentileRank(recentMeets) × 30
```

### 4.3 生命份额 (30分)

```
lifeShare = recentHoursWithFriend / myRecentOnlineHours
shareScore = sigmoid(lifeShare, medianShare) × 30
```

**设计依据**：衡量稀缺时间的分配。用户忙碌时上线10小时给A用8小时（80%份额），空闲时上线200小时给B用20小时（10%份额），A的份额更有价值。

---

## 5. 多窗口近期亲密度

除自适应窗口外，额外计算三个固定窗口供对比：

| 窗口 | 字段名 | 用途 |
|------|--------|------|
| 30天 | recentIntimacy30d | 短期热度 |
| 60天 | recentIntimacy60d | 中期热度 |
| 90天 | recentIntimacy90d | 长期热度 |

各窗口独立计算 Percentile Rank。

---

## 6. 保留率

```
保留率 = 有效时长 / 总时长
```

| 保留率 | 状态 |
|--------|------|
| 80-100% | 关系新鲜，近期频繁互动 |
| 50-80% | 正常维护 |
| 30-50% | 开始淡化 |
| <30% | 已淡化 |

---

## 7. 组合解读

| 关系强度 | 近期亲密度 | 典型情况 |
|----------|------------|----------|
| 高 | 高 | 核心好友，长期深厚且近期活跃 |
| 高 | 低 | 老朋友疏远，曾亲密但近期联系减少 |
| 低 | 高 | 新朋友升温，认识不久但互动频繁 |
| 低 | 低 | 普通关系 |

---

## 8. 命令行

```bash
python analyze_relationships.py --db VRCX.sqlite3                 # 默认半衰期120天
python analyze_relationships.py --db VRCX.sqlite3 --halflife auto # 自适应半衰期（推荐）
python analyze_relationships.py --db VRCX.sqlite3 -r              # 输出CSV排名
python analyze_relationships.py --win                             # Windows默认路径
```

| 选项 | 半衰期 | 适用场景 |
|------|--------|----------|
| `--halflife 90` | 90天 | 强调近期互动 |
| `--halflife 120` | 120天 | 平衡（默认） |
| `--halflife 180` | 180天 | 更看重历史 |
| `--halflife auto` | 90×(2-活跃度) | 自适应（推荐） |

---

## 9. 算法伪代码

```python
def analyze():
    # 1. 自适应参数
    activity = my_active_days / total_days
    halflife = 90 * (2 - activity)
    recent_window = 30 + (1 - activity) * 30

    # 2. 有效时长（指数衰减）
    for friend in friends:
        effective = sum(
            day.hours * 2**(-days_ago / halflife)
            for day in friend.interactions
        )
        friend.retention_rate = effective / friend.total_hours

    # 3. 关系强度
    for friend in friends:
        depth = percentile_rank(effective_hours) * 40
        quality = sigmoid(avg_duration, median) * 25
        stability = sqrt(active_days / total_days) * 20
        bond = calculate_bond_score(friend) * 15
        friend.relationship_strength = depth + quality + stability + bond

    # 4. 近期亲密度
    for friend in friends:
        if friend.recent_hours > 0:
            time_score = percentile_rank(recent_hours) * 40
            freq_score = percentile_rank(recent_meets) * 30
            share_score = sigmoid(life_share, median_share) * 30
            friend.recent_intimacy = time_score + freq_score + share_score
```

---

## 10. 理论参考

| 理论 | 应用 |
|------|------|
| Dunbar's Number | 社交关系分层（5/15/50/150） |
| Ebbinghaus Forgetting Curve | 指数衰减模型 |
| Social Exchange Theory | 生命份额设计 |

---

## 11. 社区检测

### 11.1 算法选择

支持两种社区检测算法：

| 算法 | 特点 | 默认 |
|------|------|------|
| **Leiden** | Louvain 改进版，保证社区内部连通 | ✓ |
| Louvain | 经典模块度优化算法 | |

**Leiden 改进**：基于 Traag et al. 2019 论文完整实现，核心改进包括：

1. **单例分区初始化**：Refinement 阶段从每个节点独立开始
2. **概率性合并**：使用随机性参数 θ = 0.01，`prob = exp(ΔQ / θ)`
3. **γ-连通性约束**：只合并模块度增益 > 0 且有边连接的节点
4. **连通性保证**：最终 BFS 检查确保每个社区内部连通

```
Louvain:  Phase1(局部移动) → Phase2(聚合) → 循环
Leiden:   Phase1(快速移动) → Refinement(概率性精炼) → Phase3(聚合) → 循环
```

### 11.2 Leiden Refinement 阶段

```python
def leiden_refinement(graph, phase1_communities, resolution, theta=0.01):
    # 1. 初始化为单例分区（每个节点独立）
    refined_comm = {node: node for node in graph.nodes}

    # 2. 对每个 Phase1 社区单独进行 Refinement
    for phase1_comm in phase1_communities:
        nodes_in_comm = get_nodes(phase1_comm)
        shuffle(nodes_in_comm)

        for node in nodes_in_comm:
            # 计算所有候选社区的模块度增益
            candidates = []
            for target_comm in neighbor_communities(node):
                delta_q = modularity_gain(node, target_comm)
                if delta_q > 0:  # γ-连通性约束
                    candidates.append((target_comm, delta_q))

            # 概率性选择（Leiden 核心改进）
            probs = [exp(delta / theta) for _, delta in candidates]
            selected = random_choice(candidates, weights=probs)
            refined_comm[node] = selected

    # 3. 连通性检查（BFS 拆分不连通社区）
    return ensure_connectivity(refined_comm)
```

### 11.3 自适应 Resolution

Resolution 参数控制社区粒度：值越高产生越多小社区，值越低产生越少大社区。

**自适应公式**：

```
resolution = 1.0 + log₁₀(avgDegree + 1) × 0.4 + density × 0.5
```

其中：
- `avgDegree = 2m / n`（平均度数）
- `density = m / (n(n-1)/2)`（网络密度）

**设计依据**：

| 因素 | 作用 | 权重 |
|------|------|------|
| 平均度数（对数） | 捕捉局部连接密度 | 0.4 |
| 网络密度 | 考虑网络规模影响 | 0.5 |

**实际数据表现**：

| 网络规模 | 平均度数 | 密度 | Resolution |
|----------|----------|------|------------|
| 200 节点, 3758 边 | 37.6 | 0.189 | 1.73 |
| 514 节点, 5119 边 | 19.9 | 0.039 | 1.55 |
| 984 节点, 51242 边 | 104.2 | 0.106 | 1.86 |

### 11.4 孤立节点处理

共同好友数为 0 的节点（通常是隐藏好友列表的用户）不参与社区检测：

- 社区检测时排除孤立节点
- 孤立节点 `community = null`
- 在社区着色模式下显示为灰色

### 11.5 算法流程

```python
def detect_communities():
    # 1. 计算自适应 resolution
    avg_degree = 2 * edges / nodes
    density = edges / max_edges
    resolution = 1.0 + log10(avg_degree + 1) * 0.4 + density * 0.5

    # 2. 排除孤立节点
    connected_nodes = [n for n in nodes if degree(n) > 0]

    # 3. 运行 Leiden/Louvain 3次，取模块度最高结果
    best_result = None
    for run in range(3):
        result = leiden_one_run(connected_nodes, resolution)
        if result.modularity > best_modularity:
            best_result = result

    # 4. 应用结果
    for node in nodes:
        if node in best_result.communities:
            node.community = best_result.communities[node]
        else:
            node.community = None  # 孤立节点
```

### 11.6 实测对比

在多个 VRC 社交网络数据集上的测试结果：

| 数据集 | 节点 | 边 | Louvain 时间 | Leiden 时间 | Louvain 社区 | Leiden 社区 | 不连通社区 |
|--------|------|-----|-------------|------------|-------------|------------|-----------|
| 样本 A | 200 | 3758 | 2.5ms | 4.7ms | 13 | 19 | 0 / 0 |
| 样本 B | 514 | 5119 | 2.8ms | 7.2ms | 42 | 71 | 0 / 0 |
| 样本 C | 242 | 3046 | 0.5ms | 1.5ms | 18 | 21 | 0 / 0 |
| 样本 D | 984 | 51242 | 12.1ms | 24.9ms | 32 | 35 | 0 / 0 |

**结论**：

| 对比项 | 结果 |
|--------|------|
| 性能 | Louvain 快 2-3 倍 |
| 社区数量 | Leiden 产生更多细粒度社区 |
| 不连通社区 | **两者均未产生** |

**分析**：

VRC 好友网络属于**中高密度社交网络**（平均度数 20-100），在这类网络上：

1. Louvain 产生不连通社区的概率本身较低
2. Leiden 的 Refinement 阶段几乎不会拆分社区
3. 两者的连通性表现实际相同

**选择建议**：

| 场景 | 推荐算法 |
|------|----------|
| 追求社区质量保证 | Leiden（默认） |
| 追求计算性能 | Louvain |
| 大规模网络（>5000节点） | Louvain |

默认使用 Leiden，因为：
- 理论上保证社区连通性
- VRC 数据规模下性能差异可接受（<25ms）
- 产生更细粒度的社区划分

### 11.7 理论参考

| 论文 | 贡献 |
|------|------|
| Blondel et al. (2008) | Louvain 算法原始论文 |
| Traag et al. (2019) | Leiden 算法，解决 Louvain 的不连通社区问题 |
| Newman (2006) | 模块度定义与优化 |
