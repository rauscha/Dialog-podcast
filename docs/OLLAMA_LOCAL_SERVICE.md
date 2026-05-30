# Ollama Local Service Setup

Date: 2026-05-11

This project can now send long, tool-free writing-room passes to a local Ollama model. The goal is not to make the whole show cheap at the cost of quality. The goal is to move the expensive drafting and rewrite work local while keeping cloud research and live fact-checking as the quality rail.

## What Ollama Provides

Ollama runs a local model server on your machine. Its default API is:

```text
http://127.0.0.1:11434
```

The generator talks to that API when a model name starts with `ollama:` or `local:`.

## Windows Install

1. Install Ollama from the official download page:

   ```text
   https://ollama.com/download
   ```

2. Open a fresh PowerShell window and verify:

   ```powershell
   ollama --version
   ```

3. Start the server if it is not already running:

   ```powershell
   ollama serve
   ```

   The desktop app often starts the server for you, but the explicit command is useful for debugging.

## Bootstrap Script

From the repo root:

```powershell
.\scripts\setup_ollama_windows.ps1 -Install -Start -Pull -ConfigureRepo -Model qwen3:14b
```

What that does:

- Installs Ollama with `winget` if it is missing.
- Starts `ollama serve` if the API is down.
- Pulls the requested model.
- Sets `dialogue_model` in `config.json` to `ollama:qwen3:14b`.
- Leaves `research_model` and `fact_check_model` on their existing cloud routes.

If you installed Ollama manually:

```powershell
.\scripts\setup_ollama_windows.ps1 -Start -Pull -ConfigureRepo -Model qwen3:14b
```

If you want models on a larger drive:

```powershell
.\scripts\setup_ollama_windows.ps1 -Start -Pull -ConfigureRepo -Model qwen3:14b -ModelDir D:\OllamaModels
```

## Smoke Test

```powershell
python scripts\ollama_smoke_test.py --model qwen3:14b
python local_first_report.py
```

Expected signs of success:

- `ollama_smoke_test.py` says the API is reachable.
- It lists `qwen3:14b` as installed.
- It prints a short sample response.
- `local_first_report.py` says the local LLM service is reachable.

## Model Choices

For your RTX 4080 16 GB machine, start with:

```powershell
ollama pull qwen3:14b
```

Why this first:

- It is large enough to test real script craft.
- It is more realistic than a tiny 7B/8B model for dialogue quality.
- It is less likely to spill heavily into system RAM than 30B+ models.

Stretch tests:

```powershell
ollama pull qwen3:30b
ollama pull llama3.1:70b
```

Those may be slow or partially CPU-bound on a 16 GB GPU. That is fine for asynchronous experiments, but judge them by audio quality and factual repair burden, not by speed.

Fast smoke-test option:

```powershell
ollama pull qwen3:8b
```

Use it to verify plumbing, not final show quality.

## Recommended Config

Quality-preserving local-heavy setup:

```json
{
  "research_model": "claude-opus-4-5",
  "dialogue_model": "ollama:qwen3:14b",
  "fact_check_model": "claude-sonnet-4-6",
  "music_prompt_model": "ollama:qwen3:14b",
  "local_llm_provider": "ollama",
  "local_llm_base_url": "http://127.0.0.1:11434",
  "local_llm_timeout_sec": 3600,
  "local_llm_num_ctx": 32768,
  "local_llm_keep_alive": "30m",
  "local_llm_think": false
}
```

`local_llm_think` defaults to `false` because writing-room stages need clean final text. Some reasoning models can spend a short response budget on hidden thinking and return no visible content when this is enabled.

What moves local:

- guest decision
- thesis/beat planning
- beat sheet
- sonic-footnote decision
- draft script
- anti-cliche rewrite
- performance polish
- host memory update
- learning path planning if `learning_path_model` is also changed
- MusicGen prompt if `music_prompt_model` is local

What stays cloud by default:

- research package
- non-fiction live fact-checking

That is intentional.

## Telegram Workflow

After setup, use:

```text
/doctor
/tts
```

`/doctor` will show the configured model names. `local_first_report.py` gives the fuller local-readiness view from PowerShell.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `ollama` is not recognized | Open a new PowerShell window after install, or use the setup script. |
| API not reachable | Run `ollama serve`, or launch the Ollama desktop app. |
| Model not installed | Run `ollama pull qwen3:14b`. |
| Very slow generations | Try `qwen3:8b` for plumbing, or keep only rewrite/performance passes local later when per-stage routing is added. |
| Local output ignores JSON | Use a stronger/larger model or keep that stage cloud-routed. Planning passes are more format-sensitive than prose passes. |
| Episodes lose factual precision | Keep `research_model` and `fact_check_model` cloud-routed. |

## References

- Ollama API docs: https://docs.ollama.com/api
- Ollama chat endpoint: https://docs.ollama.com/api/chat
- Ollama download: https://ollama.com/download
