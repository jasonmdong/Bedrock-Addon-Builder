# Getting Started with Minecraft Creator Tools MCP

The Minecraft Creator Tools (MCT) includes a [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) server that enables AI assistants — such as GitHub Copilot in VS Code, Claude Desktop, and Cursor — to create, validate, and design Minecraft Bedrock content interactively.

This guide walks you through installing MCT and configuring Visual Studio Code to use its MCP server.

## What You'll Need

Before starting, make sure you have the following:

- **Visual Studio Code** — a free code editor from Microsoft ([download here](https://code.visualstudio.com/)). Version **1.99 or later** is required for MCP support.
- A **Minecraft Creator Tools `.tgz` package** file (e.g., `mctools-int-0.0.1.tgz`) — you should have received this from your team.

## Step 1: Install Node.js

Minecraft Creator Tools runs on **Node.js**, a free runtime that lets you run tools and scripts on your computer. You'll need version **22 or higher**.

### Check if Node.js Is Already Installed

Open a terminal:

- On **Windows**: Press `Win+R`, type `cmd`, and press Enter. Or search for **Terminal** in the Start menu.
- On **macOS**: Open **Terminal** from Applications > Utilities.

Then type:

```bash
node --version
```

If you see a version number like `v22.x.x` or higher, you're all set — skip to **Step 2**. If you see an error like "'node' is not recognized" or the version is below 22, continue below.

### Download and Install Node.js

1. Go to [https://nodejs.org](https://nodejs.org).
2. Download the **LTS** (Long Term Support) version — this is the large green button on the homepage. Make sure it says version 22 or higher.
3. Run the installer and follow the prompts. Accept the default settings — the installer will set everything up for you, including adding Node.js to your system PATH.
4. **Restart your terminal** after installation (close it and open a new one).

### Verify the Installation

In a new terminal window, run:

```bash
node --version
```

You should see `v22.x.x` or higher. Also verify that **npm** (Node's package manager, which is installed alongside Node.js) is available:

```bash
npm --version
```

You should see version `10.x.x` or higher. If both commands work, you're ready to proceed.

## Step 2: Install Minecraft Creator Tools

Now you'll install the Minecraft Creator Tools package. Make sure your terminal is open and you've navigated to the folder where your `.tgz` file is located.

For example, if the file is in your Downloads folder:

```bash
cd ~/Downloads
```

On Windows, that would be:

```cmd
cd %USERPROFILE%\Downloads
```

Then run:

```bash
npm install -g ./mctools-int-0.0.1.tgz
```

Replace the filename with the actual `.tgz` file you received. This installs the tool **globally** on your computer, meaning you can use it from any folder.

> **What does `-g` mean?** The `-g` flag tells npm to install the package "globally" — making it available as a command you can run from anywhere, rather than just in one project folder.

To verify the installation worked, run:

```bash
mct-int --help
```

You should see a list of available commands. If you see "'mct-int' is not recognized", see the [Troubleshooting](#troubleshooting) section below.

## Step 3: Test the MCP Server (Optional)

You can quickly test that the MCP server launches correctly:

```bash
mct-int mcp
```

The server runs in **stdio mode** — this means it communicates through text input/output rather than showing a window. You won't see much happen, and that's normal. It's designed to be controlled by an AI assistant, not used directly. Press `Ctrl+C` to stop it.

You can also specify a working folder for the MCP server to use:

```bash
mct-int mcp -i /path/to/my/minecraft/project
```

## Step 4: Configure VS Code to Use the MCP Server

Now you need to tell VS Code where to find the Minecraft Creator Tools MCP server. There are a couple of ways to do this.

### Option A: Workspace Configuration (Recommended)

This method configures the MCP server for a specific project folder. It's the best approach because the configuration stays with the project.

1. Open your Minecraft project folder in VS Code (**File > Open Folder**).
2. In the Explorer panel on the left, look for a `.vscode` folder. If it doesn't exist, right-click in the Explorer and create a new folder called `.vscode`.
3. Inside the `.vscode` folder, create a new file called `mcp.json`.
4. Paste the following into that file and save it:

```json
{
  "servers": {
    "minecraft-creator-tools": {
      "type": "stdio",
      "command": "mct-int",
      "args": ["mcp", "-i", "${workspaceFolder}"]
    }
  }
}
```

> **What does this do?** This tells VS Code to launch `mct-int mcp` whenever an AI assistant needs Minecraft Creator Tools. The `${workspaceFolder}` part automatically fills in the path to your current project folder.

> **Note:** If VS Code shows a warning that `${workspaceFolder}` cannot be resolved, make sure you have opened a **folder** (not just a single file) via **File > Open Folder**. If it still doesn't work, your VS Code version may not support predefined variables in `mcp.json` — update to the latest version. As a workaround, you can replace `${workspaceFolder}` with an absolute path (e.g., `"C:/Users/me/my-addon"`) or omit the `-i` argument entirely — the MCP server will default to the current working directory.

### Option B: User-Level Configuration

This method makes the MCP server available in **all** your VS Code projects, without needing to create a configuration file in each one.

1. In VS Code, open the **Command Palette** from the View menu or by pressing `Ctrl+Shift+P.`.
2. In the search bar at the top, type `mcp`.
3. Find the **MCP: Open User Configuration** option and click that.
4. Add the following inside the outermost `{ }` braces:

```json
{
  "servers": {
    "minecraft-creator-tools": {
      "type": "stdio",
      "command": "mct-int",
      "args": ["mcp"]
    }
  }
}
```

> **Note:** Without the `-i` flag, the MCP server defaults to using the current working directory.

### Option C: HTTP Mode (Advanced)

If you're already running the MCT web server, the MCP endpoint is built in:

```bash
mct-int serve --adminpc <password>
```

Then configure VS Code to connect via HTTP:

```json
{
  "servers": {
    "minecraft-creator-tools": {
      "type": "sse",
      "url": "http://localhost:6126/mcp"
    }
  }
}
```

## Step 5: Start Using the MCP Tools

You're all set! Here's how to start using the Minecraft Creator Tools with GitHub Copilot:

1. Open your Minecraft project folder in VS Code (or create a new empty folder).
2. Open **GitHub Copilot Chat** by pressing `Ctrl+Shift+I` (or `Cmd+Shift+I` on macOS). You can also click the Copilot icon in the sidebar.
3. At the top of the chat panel, switch to **Agent** mode. This is the mode that allows Copilot to use MCP tools.
4. Type a request in natural language — for example, _"Create a new Minecraft add-on project called my_cool_addon"_ — and press Enter.

Copilot will automatically call the appropriate Minecraft Creator Tools to fulfill your request. You may see it ask for permission to use a tool the first time — click **Allow** to proceed.

### Available Tools

Here's what the MCP server can do. You don't need to memorize these — just describe what you want in plain English and Copilot will pick the right tool:

| Tool                         | Description                                                                                                                                                               |
| ---------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `createProject`              | Scaffold a new Minecraft Bedrock add-on project from a template (`addonStarter`, `tsStarter`, `addonFull`, `scriptBox`, `dlStarter`, `editor-scriptBox`, `editor-basics`) |
| `addItem`                    | Add content files (blocks, entities, items, spawn rules, recipes, features, etc.) to an existing project                                                                  |
| `createMinecraftContent`     | Create Minecraft Bedrock content from a simplified AI-friendly meta-schema                                                                                                |
| `getEffectiveContentSchema`  | Analyze an existing project and infer its meta-schema representation                                                                                                      |
| `validateContent`            | Validate JSON content or a base64-encoded ZIP file                                                                                                                        |
| `validateFile`               | Validate content at a specific file path                                                                                                                                  |
| `designModel`                | Design a 3D model (geometry + texture) and save it to a project folder                                                                                                    |
| `getModelTemplates`          | Get starter model templates (humanoid, small animal, block, item, bird, insect, fish, robot, etc.)                                                                        |
| `designStructure`            | Design an `.mcstructure` file using block volume definitions                                                                                                              |
| `readImageFile`              | Read an image file and return its base64 data                                                                                                                             |
| `writeImageFile`             | Write base64-encoded image data to a file                                                                                                                                 |
| `writeImageFileFromSvg`      | Convert SVG markup to PNG and write to a file                                                                                                                             |
| `writeImageFileFromPixelArt` | Create a PNG from an ASCII pixel art definition                                                                                                                           |

#### Minecraft Session Tools (requires Bedrock Dedicated Server)

| Tool                                | Description                                              |
| ----------------------------------- | -------------------------------------------------------- |
| `createMinecraftSessionWithContent` | Start a BDS session with content (`.mcaddon`/`.mcworld`) |
| `runCommandInMinecraft`             | Run a slash command in a Minecraft session               |
| `runActionSetInMinecraft`           | Run action sets and return world state                   |
| `moveSessionPlayerToLocation`       | Move a simulated player to a location                    |
| `listMinecraftSessions`             | List all active BDS sessions                             |
| `connectToMinecraftSession`         | Register an existing BDS slot as a named session         |

### Example Prompts

Try these in Copilot Agent mode:

- _"Create a new Minecraft add-on project called 'my_addon' in this folder"_
- _"Add a custom block called 'rainbow_ore' to my project"_
- _"Design a small robot mob model and save it to my project"_
- _"Validate the Minecraft content in this folder"_
- _"Create a pixel art texture for a diamond sword"_

## MCP Preferences

You can customize MCP behavior per project by creating a `.mct/mcp/prefs.json` file in your project folder:

```json
{
  "allowImageFileReadsInDescendentFolders": true,
  "allowImageFileWritesInDescendentFolders": true
}
```

The server searches up to 10 parent directories for this preferences file.

## Troubleshooting

### "mct-int" is not recognized

Make sure the global npm bin directory is in your system `PATH`. Run `npm bin -g` to find the directory, then add it to your `PATH` environment variable.

### MCP server doesn't appear in VS Code

1. Ensure you're running VS Code 1.99 or later.
2. Open the Command Palette (`Ctrl+Shift+P`) and run **MCP: List Servers** to verify the server is registered.
3. Check the Output panel (`Ctrl+Shift+U`) and select **MCP** from the dropdown for error messages.

### Tools aren't showing up in Copilot

- Make sure you're in **Agent** mode in Copilot Chat (not Ask or Edit mode).
- Verify the MCP server is running by checking **MCP: List Servers** in the Command Palette.

## Further Reading

- [Experimental SSL Support](ExperimentalSSLSupport.md) — Running the MCP server over HTTPS
- [Playwright Browser Management](PlaywrightBrowserManagement.md) — How the MCP server manages headless browsers for preview rendering
- [Project Structure](ProjectStructure.md) — Overview of the repository structure
