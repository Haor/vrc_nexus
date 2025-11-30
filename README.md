# VRChat Mutual Friends Network

A visualization tool for analyzing mutual friend relationships based on [VRCX](https://github.com/vrcx-team/VRCX) data.

![Screenshot](https://github.com/user-attachments/assets/0ca803af-7f25-49e3-9fd8-0fbd6976d42c)

## Features

### Network Visualization
- Interactive force-directed graph displaying mutual friend connections
- Zoom, pan, and drag nodes to explore the network
- Node size and color indicate the number of mutual connections
- Adjustable repulsion and link strength parameters
- Freeze layout to lock node positions

### Friend Analysis
- Mutual friends ranking sorted by connection count
- Click any node to view detailed friend information
- See the complete list of mutual friends for each person
- Search and filter friends by name
- Remove nodes from the graph for focused analysis

### Statistics
- Total friend count
- Total connection count
- Average connections per friend
- Network density percentage

### Interface
- Multi-language support: Chinese, English, Japanese
- Responsive sidebar with controls and details panel
- Export GEXF files when importing from VRCX database

## Usage

### Web Interface (`index.html`)

Open `index.html` in a browser. Two data sources are supported:

1. **GEXF File** - Load a pre-exported graph file
2. **VRCX Database** - Directly read `VRCX.sqlite3` file (parsed locally in browser, no data uploaded)

> **Prerequisite**: You must use VRCX **Nightly version** and run `Fetch Mutual Friends` in the Graph tab before using this tool.

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

## VRCX Database Path

- **Windows**: `%APPDATA%\VRCX\VRCX.sqlite3`
