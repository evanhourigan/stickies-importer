# 📝 macOS Stickies → Notion Importer

> **Seamlessly migrate your macOS Stickies to Notion with rich formatting, colors, and metadata preservation**

A powerful Python tool that imports your macOS Stickies notes into a Notion database, preserving all formatting, colors, timestamps, and content. Perfect for users transitioning from Apple's Stickies app to Notion's more powerful note-taking capabilities.

## ✨ Features

### 🎯 **Complete Data Preservation**

- **Rich Text Formatting**: Preserves bold, italic, headings, lists, and other RTF formatting
- **Original Colors**: Extracts and maps sticky note colors (Yellow, Blue, Green, Pink, Purple, Gray)
- **Accurate Timestamps**: Maintains original creation and modification dates
- **Smart Titles**: Automatically extracts meaningful titles from note content

### 🔄 **Flexible Import Modes**

- **Database Mode (`db`)**: Reads from StickiesDatabase plist file (older macOS versions)
- **RTF Directory Mode (`rtf_dir`)**: Handles individual .rtf/.rtfd files (macOS Sequoia+ / modern)
- **Auto-Detection**: Automatically falls back from DB to RTF mode when needed

### 🛡️ **Robust & Safe**

- **Duplicate Prevention**: Uses content-based hashing to avoid importing the same note twice
- **Dry Run Mode**: Preview what will be imported without making changes
- **Unicode Handling**: Properly processes special characters, emojis, and international text
- **Error Recovery**: Graceful handling of locked files, permission issues, and malformed data

### 🎛️ **Advanced Controls**

- **Timezone Support**: Configurable timezone handling for accurate timestamps
- **Selective Import**: Limit number of notes imported (useful for testing)
- **Verbose Logging**: Detailed progress and debugging information
- **Update Detection**: Smart updating of existing notes vs. creating new ones

## 🚀 Quick Start

### Prerequisites

1. **Python 3.9+** with pip
2. **Pandoc** (for RTF formatting conversion):
   ```bash
   brew install pandoc
   ```

### Installation

1. Clone this repository:

   ```bash
   git clone <repository-url>
   cd stickies-importer
   ```

2. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

3. Set up your environment:
   ```bash
   cp .env.example .env
   # Edit .env with your Notion credentials
   ```

### Configuration

Create a `.env` file with your Notion integration details:

```env
NOTION_TOKEN=secret_...  # Your Notion integration token
NOTION_DB_ID=...         # Your Notion database ID
TZ=America/New_York      # Your timezone (optional)
```

#### Setting up Notion

1. **Create a Notion Integration**:

   - Go to [notion.so/my-integrations](https://www.notion.so/my-integrations)
   - Click "New integration" and give it a name
   - Copy the "Internal Integration Token" to your `.env` file

2. **Create a Database**:

   - Create a new database in Notion with these properties:
     - `Name` (Title)
     - `Created` (Date)
     - `Modified` (Date)
     - `Color` (Text)
     - `Import Hash` (Text)

3. **Share Database with Integration**:

   - In your database, click "..." → "Add connections"
   - Select your integration

4. **Get Database ID**:
   - Copy the database URL: `https://notion.so/DATABASE_ID?v=...`
   - Extract the DATABASE_ID and add to your `.env` file

## 📖 Usage

### Basic Import

```bash
# Preview what will be imported (recommended first step)
python stickies_to_notion.py --dry-run --verbose

# Import all stickies
python stickies_to_notion.py --verbose
```

### Advanced Options

```bash
# Import specific number of notes (testing)
python stickies_to_notion.py --limit 10 --verbose

# Use specific data source
python stickies_to_notion.py --mode db --verbose           # Force database mode
python stickies_to_notion.py --mode rtf_dir --verbose      # Force RTF directory mode

# Custom paths
python stickies_to_notion.py --db-path /tmp/StickiesDatabase --verbose
python stickies_to_notion.py --rtf-dir ~/custom/stickies --verbose

# Different timezone
python stickies_to_notion.py --tz "Europe/London" --verbose

# Check what path will be used
python stickies_to_notion.py --show-db-path
```

## 🏗️ How It Works

### macOS Stickies Storage

The tool handles both legacy and modern Stickies storage formats:

- **Legacy (pre-Sequoia)**: Single `StickiesDatabase` plist file
- **Modern (Sequoia+)**: Individual `.rtfd` bundles with `TXT.rtf` files
- **Color Data**: Extracted from `.SavedStickiesState` XML file

### Import Process

1. **Discovery**: Locates your Stickies data automatically
2. **Parsing**: Extracts text, formatting, timestamps, and colors
3. **Conversion**: Transforms RTF to HTML to Notion blocks
4. **Deduplication**: Checks existing imports using content hashes
5. **Upload**: Creates/updates Notion pages with full fidelity

### Notion Structure

Each sticky becomes a Notion page with:

- **Title**: First line or meaningful content
- **Properties**: Creation date, modification date, color, import hash
- **Body**: Full formatted content as rich text blocks

## 🔧 Troubleshooting

### Common Issues

**"No pandoc was found"**

```bash
brew install pandoc
```

**"StickiesDatabase not found"**

- Quit Stickies.app first
- Try copying DB to /tmp: `cp ~/Library/StickiesDatabase /tmp/`
- Use `--show-db-path` to see what path is being checked

**"Database locked"**

- Quit Stickies.app completely
- Copy database file to temporary location
- Use `--db-path /tmp/StickiesDatabase`

**Unicode/encoding errors**

- The tool automatically handles most Unicode issues
- Special characters and emojis are supported

### Compatibility

- **macOS**: All versions with Stickies app
- **Python**: 3.9+ (uses `zoneinfo` for timezone handling)
- **Notion**: Any workspace with integration support

## 🧰 Dependencies

### Core Dependencies

- `notion-client` - Notion API integration
- `python-dotenv` - Environment configuration
- `beautifulsoup4` - HTML parsing and manipulation

### Rich Text Processing

- `pypandoc` - RTF to HTML conversion (requires pandoc binary)
- `striprtf` - Fallback RTF text extraction

### Optional Features

- `plistlib` - Built-in, for reading macOS property lists
- `zoneinfo` - Built-in Python 3.9+, for timezone handling

## 🤝 Contributing

Contributions are welcome! Areas for improvement:

- Additional export formats (Markdown, etc.)
- Attachment handling for .rtfd bundles
- Batch processing optimizations
- GUI interface

## 📄 License

MIT License

## 🙏 Acknowledgments

- Built for seamless migration from macOS Stickies to Notion
- Handles the complexity of Apple's evolving file formats
- Designed with data preservation and user experience in mind

---

**Made with ❤️ for the note-taking community**
