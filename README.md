---
title: Bedrock Add-on Builder
emoji: 🐮
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
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
- **Backend**: FastAPI (Python)
- **Frontend**: Vanilla JS, HTML5, CSS3
- **Deployment**: Dockerized for Hugging Face Spaces

## Getting Started
1. Run the app locally or access it via Hugging Face.
2. Define your mob specs in the JSON editor or use the AI assistant.
3. Design your texture in the Pixel Painter.
4. Select the mobs you want to include and click **Build Bundle**.
5. Import the generated `.mcworld` or `.mcaddon` into Minecraft!
