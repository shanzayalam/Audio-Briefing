# Briefing LangGraph (`briefing_graph.py`)

`BriefingGraph` represents the core state machine for generating briefings. It uses LangGraph to coordinate extraction, analysis, scriptwriting, audio synthesis, file export, and delivery.

## Workflow Nodes
1. **`extract_articles`**: Downloads and parses articles from provided URLs using the `newspaper` library.
2. **`analyze_articles`**: Summarizes and scores articles based on relevance using `ResearchAnalyst`.
3. **`write_script`**: Drafts a conversational news script tailored to the requested audio duration using `ScriptWriter`.
4. **`generate_audio`**: Synthesizes speech from the script (supporting providers like OpenAI TTS and Kokoro) using `AudioSpeaker`.
5. **`save_outputs`**: Saves the script (.txt), analysis summary (.json), and audio (.mp3) locally and/or uploads them to AWS S3.
6. **`send_notification`**: Delivers notifications via webhooks or SMTP emails using `EmailNotifier`.

## Tracing and Observability
- Integrates with **Opik** (an open-source LLM evaluation platform) to track node runtimes, input/output tokens, and costs.
- Tracing is automatically disabled if `OPIK_API_KEY` is not present.
