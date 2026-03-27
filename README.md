# Google Search Tool

A Playwright-based Python tool that bypasses search engine anti-scraping mechanisms to execute Google searches and extract results. It can be used directly as a command-line tool or as a Model Context Protocol (MCP) server to provide real-time search capabilities to AI assistants like Claude.


[中文文档](README.zh-CN.md)

## Key Features

- **Local SERP API Alternative**: No need to rely on paid search engine results API services, all searches are executed locally
- **Advanced Anti-Bot Detection Bypass Techniques**:
  - Intelligent browser fingerprint management that simulates real user behavior
  - Automatic saving and restoration of browser state to reduce verification frequency
  - Smart headless/headed mode switching, automatically switching to headed mode when verification is needed
  - Randomization of device and locale settings to reduce detection risk
- **Raw HTML Retrieval**: Ability to fetch the raw HTML of search result pages (with CSS and JavaScript removed) for analysis and debugging when Google's page structure changes
- **Page Screenshot**: Automatically captures and saves a full-page screenshot when saving HTML content
- **MCP Server Integration**: Provides real-time search capabilities to AI assistants like Claude without requiring additional API keys
- **Completely Open Source and Free**: All code is open source with no usage restrictions, freely customizable and extensible
- **Python Native**: Built with Python for better performance and easier deployment

## Technical Features

- **Developed with Python 3.8+**, providing excellent performance and wide compatibility
- Browser automation based on **Playwright**, supporting multiple browser engines
- Command-line parameter support for search keywords
- **MCP server support** for AI assistant integration
- Returns search results with title, link, and snippet
- Option to retrieve raw HTML of search result pages for analysis
- JSON format output
- Support for both headless and headed modes (for debugging)
- Detailed logging output
- Robust error handling
- Browser state saving and restoration to effectively avoid anti-bot detection
- **Anti-bot protection mechanisms** at multiple levels

## Installation

```bash
# Install from source
git clone https://github.com/iwanghc/mcp_web_search.git
cd mcp_web_search

# Install Python dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium
```

## Usage

### Command Line Tool

```bash
# Direct command line usage
python cli.py "search keywords"

# Using command line options
python cli.py --limit 5 --timeout 30000 "search keywords"

# Get raw HTML of search result page
python cli.py --get-html "search keywords"

# Get HTML and save to file
python cli.py --get-html --save-html "search keywords"
```

### MCP Server

```bash
# Configure model API KEY and other information in dotenv.env
# USE MCP server
python -m mcp_integration.client
```

#### Command Line Options

- `-l, --limit <number>`: Result count limit (default: 10)
- `-t, --timeout <number>`: Timeout time in milliseconds (default: 30000)
- `--no-headless`: Show browser interface (for debugging)
- `--remote-debugging-port <number>`: Enable remote debugging port (default: 9222)
- `--state-file <path>`: Browser state file path (default: ./browser-state.json)
- `--no-save-state`: Don't save browser state
- `--get-html`: Get raw HTML of search result page instead of parsed results
- `--save-html`: Save HTML to file (use with --get-html)
- `--html-output <path>`: Specify HTML output file path (use with --get-html and --save-html)
- `-V, --version`: Show version number
- `-h, --help`: Show help information

#### Output Example

```json
{
  "query": "deepseek",
  "results": [
    {
      "title": "DeepSeek",
      "link": "https://www.deepseek.com/",
      "snippet": "DeepSeek-R1 is now live and open source, rivaling OpenAI's Model o1. Available on web, app, and API. Click for details. Into ..."
    },
    {
      "title": "DeepSeek",
      "link": "https://www.deepseek.com/",
      "snippet": "DeepSeek-R1 is now live and open source, rivaling OpenAI's Model o1. Available on web, app, and API. Click for details. Into ..."
    },
    {
      "title": "deepseek-ai/DeepSeek-V3",
      "link": "https://github.com/deepseek-ai/DeepSeek-V3",
      "snippet": "We present DeepSeek-V3, a strong Mixture-of-Experts (MoE) language model with 671B total parameters with 37B activated for each token."
    }
    // More results...
  ]
}
```

#### HTML Output Example

When using the `--get-html` option, the output will contain HTML content-related information:

```json
{
  "query": "playwright automation",
  "url": "https://www.google.com/",
  "originalHtmlLength": 1291733,
  "cleanedHtmlLength": 456789,
  "htmlPreview": "<!DOCTYPE html><html itemscope=\"\" itemtype=\"http://schema.org/SearchResultsPage\" lang=\"zh-CN\"><head><meta charset=\"UTF-8\"><meta content=\"dark light\" name=\"color-scheme\"><meta content=\"origin\" name=\"referrer\">..."
}
```

If you also use the `--save-html` option, the output will also include the HTML saved file path:

```json
{
  "query": "playwright automation",
  "url": "https://www.google.com/",
  "originalHtmlLength": 1292241,
  "cleanedHtmlLength": 458976,
  "savedPath": "./google-search-html/playwright_automation-2025-04-06T03-30-06-852Z.html",
  "screenshotPath": "./google-search-html/playwright_automation-2025-04-06T03-30-06-852Z.png",
  "htmlPreview": "<!DOCTYPE html><html itemscope=\"\" itemtype=\"http://schema.org/SearchResultsPage\" lang=\"zh-CN\">..."
}
```

### MCP Server

This project provides Model Context Protocol (MCP) server functionality, allowing AI assistants like Claude to directly use Google search capabilities. MCP is an open protocol that enables AI assistants to securely access external tools and data.

#### Integration with Claude Desktop

1. Edit Claude Desktop configuration file
   - Mac: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\Claude\claude_desktop_config.json`
     - Usually located at `C:\Users\username\AppData\Roaming\Claude\claude_desktop_config.json`
     - You can enter `%APPDATA%\Claude` in Windows Explorer address bar to access directly

2. Add server configuration and restart Claude

```json
{
  "mcpServers": {
    "google-search": {
      "command": "python",
      "args": ["mcp_server_simple.py"]
    }
  }
}
```

After integration, you can directly use search functionality in Claude, such as "Search for the latest AI research".

## Project Structure

```
google-search/
├── Core Functions/
│   ├── google_search/
│   │   ├── engine.py              # Search engine implementation
│   │   ├── browser_manager.py     # Browser management and automation
│   │   ├── search_executor.py     # Search execution logic
│   │   ├── html_extractor.py      # HTML parsing and extraction
│   │   ├── fingerprint.py         # Browser fingerprint management
│   │   ├── utils.py               # Utility functions
│   │   └── __init__.py            # Package initialization
│   └── cli.py                     # Command line interface
├── MCP Integration/
│   ├── mcp_integration/
│   │   ├── server.py              # MCP server implementation
│   │   ├── client.py              # MCP client implementation
│   │   └── __init__.py            # Package initialization
├── Common Utilities/
│   ├── common/
│   │   ├── logger.py              # Logging system
│   │   ├── types.py               # Common data types
│   │   └── __init__.py            # Package initialization
├── Configuration & Runtime/
│   ├── requirements.txt            # Python dependencies
│   ├── dotenv.env                  # Environment variables
│   ├── browser-state.json          # Browser state persistence
│   ├── browser-state-fingerprint.json # Browser fingerprint data
│   └── .gitignore                  # Git ignore rules
├── Documentation/
│   ├── README.md                   # English documentation
│   ├── README.zh-CN.md             # Chinese documentation
│   └── google_search/REFACTOR_README.md # Refactoring notes
├── Development/
│   ├── .vscode/                    # VS Code configuration
│   └── logs/                       # Application logs
└── Other/
    └── __pycache__/                # Python cache files
```

## Technology Stack

- **Python 3.8+**: Development language, providing excellent performance and compatibility
- **Playwright**: For browser automation, supporting multiple browsers
- **MCP SDK**: For implementing MCP server development tools
- **asyncio**: Python's standard library for asynchronous I/O
- **aiofiles**: Asynchronous file operations

## Development Guide

All commands can be run in the project root directory:

```bash
# Install dependencies
pip install -r requirements.txt

# Install Playwright browsers
playwright install chromium

# Run CLI tool
python cli.py "search keywords"

# Start MCP server
python mcp_server_simple.py

# Test MCP client
python mcp_client_enhanced.py
```

## Error Handling

The tool has built-in robust error handling mechanisms:

- Provides friendly error information when browser startup fails
- Automatically returns error status when network connection issues occur
- Provides detailed logs when search result parsing fails
- Gracefully exits and returns useful information in timeout situations

## Notes

### General Notes

- This tool is for learning and research purposes only
- Please comply with Google's terms of service and policies
- Don't send requests too frequently to avoid being blocked by Google
- Some regions may require proxies to access Google
- Playwright requires browser installation, which will be automatically downloaded on first use

### State Files

- State files contain browser cookies and storage data, please keep them safe
- Using state files can effectively avoid Google's anti-bot detection and improve search success rate

### MCP Server

- When using MCP server, please ensure Claude Desktop is updated to the latest version
- When configuring Claude Desktop, please use absolute paths pointing to MCP server files

### Windows Environment Special Notes

- In Windows environment, first run may require administrator privileges to install Playwright browsers
- If you encounter permission issues, try running Command Prompt or PowerShell as administrator
- Windows Firewall may block Playwright browser network connections, please allow access when prompted
- Browser state files are saved by default in the user's home directory under `.google-search-browser-state.json`
- Log files are saved in the system temporary directory under `google-search-logs` folder

## Comparison with Commercial SERP APIs

Compared to paid search engine results API services (such as SerpAPI), this project provides the following advantages:

- **Completely Free**: No API call fees required
- **Local Execution**: All searches are executed locally, no dependency on third-party services
- **Privacy Protection**: Search queries are not recorded by third parties
- **Customizability**: Completely open source, can be modified and extended as needed
- **No Usage Restrictions**: Not subject to API call count or frequency limitations
- **MCP Integration**: Native support for integration with AI assistants like Claude

## Anti-Bot Protection

This project implements multiple layers of anti-bot protection:

### Client Level Protection
- Request interval control with random delays
- Timeout protection for tool calls
- Intelligent error handling

### Server Level Protection
- Request frequency limiting
- Random delays between requests 
- Global request counting and management

### Search Level Protection
- Browser fingerprint randomization
- Device and locale randomization
- Browser state management
- Automatic CAPTCHA detection and handling

## Anti-Bot & Stealth Modes

This project provides multiple operational modes to improve reliability when searching against Google while reducing the chance of triggering anti-bot defenses.

- **Persistent Contexts (default)**: the tool uses Playwright's persistent Chromium context (stored under `./user_data` and `./browser-state.json`). Persisting state preserves cookies, localStorage, and other session artifacts so Google learns that requests come from an established browser profile. Over time this significantly reduces captcha frequency and improves the tool's reputation with Google's systems.

- **Basic View (`--basic-view`, alias `-b` / `--gbv`)**: when enabled the tool appends `&gbv=1` to the search URL (Google Basic Variant). This forces a legacy, mostly static HTML page that does not execute client-side JavaScript. Because modern fingerprinting and behavioral scripts rely on JavaScript, the Basic View bypasses a large portion of JS-based bot detection. Use this mode when modern searches yield CAPTCHAs or when you need a faster, more stable extraction surface.

- **Auto‑Retry Logic**: the engine will automatically attempt to recover from a CAPTCHA in Modern View by retrying the search once using Basic View. The fallback is performed transparently when a CAPTCHA is detected, so callers don't need to manually switch modes in many cases.

When to use each mode:

- Start with the default (persistent context, modern UI) — it provides the most natural results and preserves session behavior.
- If you encounter recurrent CAPTCHAs or need deterministic HTML structure, use `--basic-view` (or `-b` / `--gbv`).

Security & Compliance:

- Respect Google's terms of service. This project is intended for research and debugging; avoid large-scale automated scraping without proper authorization.


## Performance

- **Response Time**: Typically 5-15 seconds
- **Success Rate**: 95%+ (with state files)
- **Concurrency**: Supports asynchronous operations
- **Memory Usage**: Optimized with cleanup after each call
- **Stability**: Robust error recovery and timeout handling

## Recent Changes

- Removed the top-level `Dockerfile`; use `Dockerfile.ubuntu` for building the Ubuntu-based image.
- MCP server now supports HTTP/SSE mode (Starlette + `SseServerTransport`). To run in SSE mode:

  ```bash
  MCP_SSE=1 MCP_SSE_HOST=0.0.0.0 MCP_SSE_PORT=8000 python -m mcp_integration.server
  ```

- A `/health` endpoint is available at `http://<host>:<port>/health` (returns `ok`) for container healthchecks.
- The MCP `google-search` tool now returns structured JSON (dict) as the tool result to avoid double-encoding JSON strings — clients receive a single valid JSON object.
- Process locale defaults are set to `en_US.UTF-8` inside the server process to avoid unexpected locale-dependent behavior in Playwright and logs.
- Minor lint fixes applied to `mcp_integration/server.py`.
