# VRChat Mutual Friends Network

A visualization tool for analyzing mutual friend relationships based on [VRCX](https://github.com/vrcx-team/VRCX) data.

![Screenshot](https://github.com/user-attachments/assets/21237b6f-f0d9-4f34-ba8d-29f305152ea2)

## Features

### Network Visualization
- Interactive force-directed graph displaying mutual friend connections
- Zoom, pan, and drag nodes to explore the network
- Node size indicates the number of mutual connections
- Adjustable repulsion and link strength parameters
- Freeze layout to lock node positions

### Color Modes
- **Connections**: Node color by mutual friend count (gray-pink gradient)
- **Trust Level**: VRChat trust level colors (Visitor/New User/User/Known User/Trusted User)
- **Relationship Strength**: Purple-red gradient based on long-term relationship depth (0-100 score)
- **Playtime**: Cyan-blue gradient based on relative play time

### Relationship Metrics
- **Relationship Strength**: Long-term accumulated relationship depth with decay mechanism
- **Recent Intimacy**: Recent interaction intensity with configurable time windows (30/60/90 days)
- Detailed score breakdown panel showing individual metric components

### Ranking & Export
- Multi-dimension ranking: Mutual friends / Relationship strength / Recent intimacy / Playtime
- CSV export for relationship strength ranking, intimacy ranking, or full data
- Data completeness indicator showing date range, total days, activity rate, and half-life

### Friend Analysis
- Click any node to view detailed friend information
- Trust level badge with color coding
- Relationship metrics with ranking position
- Raw data: total playtime, effective hours, retention rate, meet count
- Complete list of mutual friends for each person
- Search and filter friends by name
- Remove nodes from the graph for focused analysis

### Statistics
- Total friend count
- Total connection count
- Average connections per friend
- Network density percentage

### Interface
- Multi-language support: Chinese, English, Japanese
- Dark theme with cyberpunk aesthetic
- Responsive design with mobile support
- Collapsible color mode toolbar
- Export GEXF files when importing from VRCX database

## Usage

### Web Interface (`index.html`)

Open `index.html` in a browser. Two data sources are supported:

1. **GEXF File** - Load a pre-exported graph file
2. **VRCX Database** - Directly read `VRCX.sqlite3` file (parsed locally in browser, no data uploaded)

> **Prerequisite**: You must use VRCX **Stable 2025.12.06 or later** and run `Start Fetch` in the Mutual Friend Network section of the Chart tab before using this tool.

### Python Script (`vrcx_to_gexf.py`)

Command-line tool to export VRCX database to GEXF format:

```bash
# Use VRCX.sqlite3 in current directory
python vrcx_to_gexf.py

# Specify database path
python vrcx_to_gexf.py --db /path/to/VRCX.sqlite3

# Use Windows default path (%APPDATA%\VRCX\VRCX.sqlite3)
python vrcx_to_gexf.py --win

# Specify output file
python vrcx_to_gexf.py --output my_network.gexf
```

### Relationship Analysis Script (`analyze_relationships.py`)

Advanced relationship strength and recent intimacy analysis with adaptive decay mechanism:

```bash
# Basic analysis
python RELATIONSHIP_ANALYSIS/analyze_relationships.py --db /path/to/VRCX.sqlite3

# Export rankings to CSV
python RELATIONSHIP_ANALYSIS/analyze_relationships.py --db VRCX.sqlite3 -r

# Custom half-life and recent window
python RELATIONSHIP_ANALYSIS/analyze_relationships.py --db VRCX.sqlite3 --halflife 180 --recent 60

# Adaptive mode (recommended)
python RELATIONSHIP_ANALYSIS/analyze_relationships.py --db VRCX.sqlite3 --halflife auto --recent auto
```

**Features:**
- **Relationship Strength**: Long-term accumulated relationship depth with decay mechanism
- **Recent Intimacy**: Recent interaction intensity (configurable time window)
- **Adaptive Parameters**: Auto-adjusts half-life (90-180 days) and recent window (30-60 days) based on user activity
- **CSV Export**: Generate ranking files for both metrics

See `RELATIONSHIP_ANALYSIS/ALGORITHM_DESIGN.md` for detailed algorithm design philosophy.

## VRCX Database Path

- **Windows**: `%APPDATA%\VRCX\VRCX.sqlite3`
