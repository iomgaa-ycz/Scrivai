<!-- This is a Chinese translation of docs/getting-started/installation.md. -->
<!-- Keep in sync. When English changes, update this file or open an issue tagged docs:zh-sync. -->

# 安装

## 环境要求

- Python **3.11** 或更高版本
- Anthropic API 密钥（或兼容网关）

## 从 PyPI 安装

```bash
pip install scrivai
```

## 从源码安装（开发模式）

```bash
git clone https://github.com/iomgaa-ycz/Scrivai.git
cd Scrivai
pip install -e ".[dev]"
```

## 配置

复制示例 env 文件并填入你的配置值：

```bash
cp .env.example .env
```

| 变量 | 是否必填 | 说明 |
|---|---|---|
| `ANTHROPIC_API_KEY` | **是** | 你的 Anthropic API 密钥（或网关 token） |
| `ANTHROPIC_BASE_URL` | 否 | 覆盖 API 基础 URL（例如用于私有网关） |
| `SCRIVAI_DEFAULT_MODEL` | 否 | `ModelConfig` 使用的默认模型 ID（如 `claude-sonnet-4-20250514`） |
| `SCRIVAI_DEFAULT_PROVIDER` | 否 | 写入轨迹记录的供应商标签（如 `anthropic`） |

### 使用兼容网关

如果你通过代理或私有 LLM 网关路由请求，将 `ANTHROPIC_BASE_URL` 设置为网关的基础 URL。Claude Agent SDK 会自动读取该变量，无需修改代码。

```bash
export ANTHROPIC_BASE_URL=https://my-gateway.example.com
export ANTHROPIC_API_KEY=my-gateway-key
export SCRIVAI_DEFAULT_MODEL=claude-sonnet-4-20250514
```

### 验证安装

```python
import scrivai
print(scrivai.__version__)
```
