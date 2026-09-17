# Research Agent

Research Agent is a **Windows chat app** that runs on your computer. You can ask questions, attach PDFs or images, and search scholarly sources. Answers come from AI models on your machine (through Ollama), not from a cloud account.

Chats stay on your PC. The app does not upload your conversations.

---

## Before you start (install these once)

You need a Windows 10 or 11 PC, an internet connection for the first setup, and about **10 GB free** on a drive that is **not C:** (usually **D:**).

Install these three programs if you do not already have them. Use the default options, and restart the computer if an installer asks you to.

1. **Git** — [https://git-scm.com/download/win](https://git-scm.com/download/win)
2. **Python 3.10 or newer** — [https://www.python.org/downloads/](https://www.python.org/downloads/)  
   On the first installer screen, tick **Add python.exe to PATH**.
3. **Node.js LTS** — [https://nodejs.org/](https://nodejs.org/)

You do **not** need Visual Studio or Rust to use the chat in a browser.

---

## First time only: copy the project and set it up

### 1. Open PowerShell

Click the Start menu, type `PowerShell`, and open **Windows PowerShell**.

### 2. Download the project

Copy this whole block, paste it into PowerShell, and press Enter:

```powershell
cd D:\Projects
git clone https://github.com/ahmadimran2001/ResearchAgent.git
cd ResearchAgent
```

If you do not have a `D:\Projects` folder, use your Documents folder instead:

```powershell
cd $HOME\Documents
git clone https://github.com/ahmadimran2001/ResearchAgent.git
cd ResearchAgent
```

### 3. Install the app’s own files

Stay in that folder and run:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup-windows.ps1
```

This can take several minutes. Wait until it finishes with no red error.

### 4. Install the AI (Ollama + Phi-4 Mini)

This step puts the AI program and the Phi-4 Mini model **off the C: drive** (default: `D:\DevTools\Ollama` and `D:\Caches\Ollama\models`). It can download a few GB and may take 10–20 minutes.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-ollama-phi4.ps1
```

**If you already use Ollama and already have Phi-4 Mini**, skip this step.

**If you have no D: drive**, install to another non-C: drive, for example E:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\install-ollama-phi4.ps1 -InstallRoot E:\Tools\Ollama -ModelsRoot E:\Caches\Ollama\models
```

Leave Ollama running after this. If Windows asks for network permission, allow it.

---

## Every time you want to use the app

1. Open PowerShell.
2. Go to the project folder:

```powershell
cd D:\Projects\ResearchAgent
```

(Use the folder you cloned into if it is different.)

3. Start the app:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start.ps1
```

4. A browser tab should open at [http://127.0.0.1:1420](http://127.0.0.1:1420). If it does not, open that address yourself.
5. Wait until the model menu shows **Phi-4 Mini** as ready (not “unavailable”). Then type a question and press Enter.

Keep the PowerShell window open while you chat. To stop the app, click that window and press **Ctrl+C**, or close the window.

The first answer after a restart can be slow while the model loads. Later answers in the same session are usually faster. Leave Ollama running in the background.

---

## If something goes wrong

| What you see | What to try |
| --- | --- |
| `python` / `py` was not found | Reinstall Python and tick **Add python.exe to PATH**, then open a **new** PowerShell window. |
| `npm` was not found | Reinstall Node.js LTS, then open a **new** PowerShell window. |
| `git` was not found | Install Git, then open a **new** PowerShell window. |
| Backend failed to start | Read `data\logs\sidecar-stderr.log` in the project folder. Close other PowerShell windows that might already be running the app. |
| Model not ready / Phi-4 Mini unavailable | Run `scripts\install-ollama-phi4.ps1`. Make sure Ollama is running. |
| Script cannot use C: | Pass a D: or E: folder as shown in step 4. |
| Page will not load | Confirm `scripts\start.ps1` is still running, then visit http://127.0.0.1:1420 |

---

## What this app will not do

- It is not a doctor, lawyer, or publisher. Check important facts yourself.
- It can be wrong, including about papers and citations.
- It is meant for one person on a normal laptop (about 8 GB RAM). Do not turn on **Compare** unless you have two models and extra memory.

---

## For developers (optional)

Browser chat is enough for normal use. Packaging a Windows installer needs Rust and Visual Studio C++ tools.

```powershell
powershell -ExecutionPolicy Bypass -File scripts\configure-native-tools.ps1
powershell -ExecutionPolicy Bypass -File scripts\install-build-tools.ps1
powershell -ExecutionPolicy Bypass -File scripts\package-windows.ps1
```

Tests:

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
npm test
npm run typecheck
```

More detail: `docs/architecture.md`, `docs/security.md`, `docs/qa-strategy.md`, `THIRD_PARTY_NOTICES.md`.

---

## License

This project’s code is MIT licensed; see `LICENSE`. Phi-4 Mini, Ollama, and any papers or files you add keep their own terms.
