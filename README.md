# VRChat 共同好友网络

基于 [VRCX](https://github.com/vrcx-team/VRCX) 数据的共同好友关系可视化分析工具。

**[English](README_EN.md)**

![Screenshot](https://github.com/user-attachments/assets/21237b6f-f0d9-4f34-ba8d-29f305152ea2)

## 功能

### 网络可视化
- 交互式力导向图展示共同好友连接
- 支持缩放、平移、拖拽节点
- 节点大小表示共同好友数量
- 可调节斥力和连接强度参数
- 冻结布局锁定节点位置

### 着色模式
- **共同好友数**：灰色到粉色渐变
- **信任等级**：VRChat 官方信任等级配色（Visitor/New User/User/Known User/Trusted User）
- **关系强度**：紫红渐变，基于长期关系深度（0-100分）
- **游玩时长**：青色渐变，基于相对游玩时长
- **社区**：按检测到的社区分组着色（Louvain 算法）

### 关系指标
- **关系强度**：长期累积的关系深度，带时间衰减机制
- **近期亲密度**：近期互动热度，支持多时间窗口（30/60/90天）
- 得分明细面板展示各维度子分数

### 排名与导出
- 多维度排名：共同好友 / 关系强度 / 近期亲密度 / 游玩时长
- CSV 导出：关系强度排名、亲密度排名或完整数据
- 数据完整度指示器：显示日期范围、总天数、活跃率、半衰期

### 好友分析
- 点击节点查看详细信息
- 信任等级徽章（带颜色）
- 关系指标及排名
- 原始数据：总游玩时长、有效时长、保留率、见面次数
- 聚类系数和社区归属
- 共同好友列表
- 搜索和筛选好友
- 从图中移除节点进行聚焦分析

### 统计信息
- 好友总数
- 连接总数
- 平均连接数
- 网络密度
- 平均聚类系数
- 社区数量

### 社区检测
- **Louvain 算法**：基于模块度的层次聚合社区检测
- **自适应分辨率**：根据网络密度自动调整
- **分辨率滑块**：手动调节（0.5-4.0）
- **多次运行优化**：运行 3 次取最高模块度结果

### 界面
- 多语言支持：中文、英文、日文
- 深色主题
- 响应式设计
- 可折叠着色模式工具栏
- 从 VRCX 数据库导入时可导出 GEXF 文件

## 使用方法

### 网页界面 (`index.html`)

在浏览器中打开 `index.html`，支持两种数据源：

1. **GEXF 文件** - 加载预导出的图文件
2. **VRCX 数据库** - 直接读取 `VRCX.sqlite3` 文件（本地解析，数据不会上传）

> **前置条件**：需使用 VRCX **Stable 2025.12.06 或更高版本**，并在 Chart 标签页的 Mutual Friend Network 中执行 `Start Fetch`。

### Python 脚本 (`vrcx_to_gexf.py`)

导出 VRCX 数据库为 GEXF 格式：

```bash
# 使用当前目录的 VRCX.sqlite3
python vrcx_to_gexf.py

# 指定数据库路径
python vrcx_to_gexf.py --db /path/to/VRCX.sqlite3

# 使用 Windows 默认路径 (%APPDATA%\VRCX\VRCX.sqlite3)
python vrcx_to_gexf.py --win

# 指定输出文件
python vrcx_to_gexf.py --output my_network.gexf
```

### 关系分析脚本 (`analyze_relationships.py`)

高级关系强度和近期亲密度分析，支持自适应衰减机制：

```bash
# 基本分析
python RELATIONSHIP_ANALYSIS/analyze_relationships.py --db /path/to/VRCX.sqlite3

# 导出排名 CSV
python RELATIONSHIP_ANALYSIS/analyze_relationships.py --db VRCX.sqlite3 -r

# 自定义半衰期和近期窗口
python RELATIONSHIP_ANALYSIS/analyze_relationships.py --db VRCX.sqlite3 --halflife 180 --recent 60

# 自适应模式（推荐）
python RELATIONSHIP_ANALYSIS/analyze_relationships.py --db VRCX.sqlite3 --halflife auto --recent auto
```

**功能说明**：
- **关系强度**：长期累积的关系深度，带衰减机制
- **近期亲密度**：近期互动热度（可配置时间窗口）
- **自适应参数**：根据用户活跃度自动调整半衰期（90-180天）和近期窗口（30-60天）
- **CSV 导出**：生成两个指标的排名文件

详见 `RELATIONSHIP_ANALYSIS/ALGORITHM_DESIGN.md` 了解算法设计。

## VRCX 数据库路径

- **Windows**: `%APPDATA%\VRCX\VRCX.sqlite3`
