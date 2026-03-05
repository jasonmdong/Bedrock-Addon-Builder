---
title: Bedrock Add-on Builder
emoji: 🐮
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: true
---

A preview is available here: https://jasonmdong-baobuilder.hf.space/

# Bedrock Add-on Builder
A powerful, web-based tool for creating Minecraft Bedrock Edition Add-ons (Behavior and Resource packs) with ease.

## Features
- **Interactive JSON Editor**: Customize mob properties like health, damage, speed, and collision boxes.
- **AI-Powered Mob Design**: Integrated LLM assistant to help you rewrite and refine mob specifications using natural language.
- **Multi-Mob Management**: Sidebar interface to manage multiple custom entities in a single bundle.
- **Automated Bundling**: Instantly generate `.mcaddon`, `.mcworld`, and individual `.mcpack` files.
- **Custom Textures**: Built-in Pixel Painter to design your mob skins directly in the browser.
- **Pack Merging**: Upload existing packs to merge them into your custom project.

## Tech Stack
- **Backend**: FastAPI (Python 3.12)
- **Frontend**: Vanilla JS, HTML5, CSS3
- **LLM Integration**: OpenAI, Google Gemini, Anthropic Claude
- **Deployment**: Dockerized for Hugging Face Spaces
- **Server**: Uvicorn with Gunicorn for production

## Project Structure
```
Bedrock-Addon-Builder/
├── backend/
│   ├── data/              # Vanilla mob data and references
│   ├── schemas/           # JSON schemas for validation
│   ├── app.py            # FastAPI application entry point
│   ├── builders.py       # Addon building logic
│   ├── core.py           # Core utilities
│   ├── llm.py            # LLM integration
│   ├── packaging.py      # Pack generation and merging
│   ├── routes.py         # API route handlers
│   ├── schemas_loader.py # Schema validation
│   └── spec_utils.py     # Spec manipulation utilities
├── data/
│   ├── specs/            # Custom mob specifications
│   └── templates/        # Mob templates
├── frontend/
│   ├── index.html        # Main web interface
│   └── styles.css        # Application styles
├── Dockerfile            # Container configuration
├── requirements.txt      # Python dependencies
└── run.py               # Local development server
```

## Getting Started

### Prerequisites
- Python 3.12 or higher
- pip (Python package manager)

### Local Development

1. **Clone the repository**
```bash
git clone https://github.com/jasonmdong/Bedrock-Addon-Builder
cd Bedrock-Addon-Builder
```

2. **Install dependencies**
```bash
pip install -r requirements.txt
```

3. **Set up environment variables** (optional, for LLM features)
```bash
export OPENAI_API_KEY="your-key-here"
# or
export GOOGLE_API_KEY="your-key-here"
# or
export ANTHROPIC_API_KEY="your-key-here"
```

4. **Run the development server**
```bash
python run.py
```

5. **Access the application**
Open your browser to `http://localhost:7860` or `http://127.0.0.1:7860`

### Docker Deployment

```bash
docker build -t bedrock-addon-builder .
docker run -p 7860:7860 bedrock-addon-builder
```

## Usage Guide

1. **Create a Custom Mob**
   - Click "New Mob" in the sidebar
   - Define your mob specs in the JSON editor or use the AI assistant
   - Customize properties: health, damage, speed, collision boxes, etc.

2. **Design Textures**
   - Use the built-in Pixel Painter to create mob skins
   - Preview your texture in real-time

3. **Use AI Assistant**
   - Describe your mob in natural language
   - Let the LLM help refine and rewrite specifications

4. **Build and Export**
   - Select the mobs you want to include
   - Click **Build Bundle**
   - Download `.mcaddon`, `.mcworld`, or individual `.mcpack` files

5. **Import to Minecraft**
   - Open the downloaded file with Minecraft Bedrock Edition
   - Enable the behavior and resource packs in your world settings

## Contributing
Contributions are welcome! Please feel free to submit pull requests or open issues for bugs and feature requests.

## License
This project is open source and available for educational and personal use.
