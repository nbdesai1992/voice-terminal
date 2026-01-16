# Voice Terminal

A macOS menubar app that lets you speak to type into any application. Perfect for terminals, VS Code, or anywhere that doesn't support native dictation.

## How It Works

1. App runs in your menubar (🎤 icon)
2. Click on any window/terminal to focus it
3. Hold **Cmd+Shift+V** and speak
4. Release the hotkey
5. Your speech is transcribed and typed into the focused window

## Setup

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

### 2. Set Your OpenAI API Key

Edit the `.env` file and add your key:

```
OPENAI_API_KEY=sk-your-actual-key-here
```

### 3. Grant Permissions

On first run, macOS will prompt for:

- **Microphone Access**: Required for recording audio
- **Accessibility Access**: Required for typing into other apps

Go to **System Preferences > Privacy & Security** to grant these if needed.

### 4. Run the App

```bash
python voice_terminal.py
```

## Usage

| Action | Result |
|--------|--------|
| Hold **Cmd+Shift+V** | Start recording (icon turns 🔴) |
| Speak | Your voice is captured |
| Release hotkey | Audio is transcribed and typed |

The menubar icon shows status:
- 🎤 Ready
- 🔴 Recording
- ⏳ Processing

## Tips

- Speak clearly and at a normal pace
- Short phrases work best
- Click to focus the target window/pane before pressing the hotkey
- Works with VS Code terminals, iTerm, standard Terminal, or any text field

## Cost

Uses OpenAI's Whisper API at ~$0.006 per minute of audio. A typical command costs a fraction of a cent.

## Troubleshooting

**"API Key Missing" alert**
- Make sure `OPENAI_API_KEY` is set in your environment
- Restart the app after setting it

**Text not appearing in target window**
- Grant Accessibility permission in System Preferences
- Make sure the target window is focused before pressing hotkey

**No audio captured**
- Grant Microphone permission in System Preferences
- Check that your mic is working in other apps
