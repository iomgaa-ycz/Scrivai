# Installation

## Requirements

- Python **3.11** or later
- An Anthropic API key (or a compatible gateway)

## Install from PyPI

```bash
pip install scrivai
```

## Install from Source (development)

```bash
git clone https://github.com/iomgaa-ycz/Scrivai.git
cd Scrivai
pip install -e ".[dev]"
```

## Environment Configuration

Copy the example env file and fill in your values:

```bash
cp .env.example .env
```

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | **Yes** | Your Anthropic API key (or gateway token) |
| `ANTHROPIC_BASE_URL` | No | Override the API base URL (e.g. for a private gateway) |
| `SCRIVAI_DEFAULT_MODEL` | No | Default model ID used by `ModelConfig` (e.g. `claude-sonnet-4-20250514`) |
| `SCRIVAI_DEFAULT_PROVIDER` | No | Provider label written to trajectory records (e.g. `anthropic`) |

### OCR Configuration

The `to_markdown()` function supports pluggable OCR backends. Configure via environment variables or function parameters (parameters take precedence).

| Variable | Default | Description |
|---|---|---|
| `SCRIVAI_OCR_BACKEND` | `mineru` | OCR backend: `mineru` (MinerU local pipeline, default), `glm` (ZhipuAI cloud), or `monkey` (self-hosted MonkeyOCR) |
| `SCRIVAI_GLM_API_KEY` | — | API key for GLM-OCR (required when using `glm` backend; get from [open.bigmodel.cn](https://open.bigmodel.cn)) |
| `SCRIVAI_OCR_BASE_URL` | — | MonkeyOCR service URL (required when using `monkey` backend) |
| `SCRIVAI_OCR_UPLOAD_RATE` | `512000` | MonkeyOCR upload rate limit in bytes/s (0 = unlimited) |

### Using a Private Gateway

If you route through a proxy or private LLM gateway, set `ANTHROPIC_BASE_URL` to the gateway's base URL. The Claude Agent SDK reads this variable automatically — no code changes are required.

```bash
export ANTHROPIC_BASE_URL=https://my-gateway.example.com
export ANTHROPIC_API_KEY=my-gateway-key
export SCRIVAI_DEFAULT_MODEL=claude-sonnet-4-20250514
```

### Verify the Installation

```python
import scrivai
print(scrivai.__version__)
```
