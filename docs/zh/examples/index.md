<!-- This is a Chinese translation of docs/examples/index.md. -->
<!-- Keep in sync. When English changes, update this file or open an issue tagged docs:zh-sync. -->

# 示例

`examples/` 目录包含三个端到端脚本，演示 Scrivai 的主要工作流。

## 示例脚本

| 脚本 | 说明 | LLM 调用次数 | 典型耗时 |
|---|---|---|---|
| `examples/01_audit_single_doc.py` | 使用 `AuditorPES` 按规则集审核单个文档，输出发现列表和裁定结论。 | ~6 | ~30 秒 |
| `examples/02_generate_with_revision.py` | 使用 `GeneratorPES` 从模板生成文档，然后自审并最多修订 2 次。 | ~12 | ~60 秒 |
| `examples/03_evolve_skill_workflow.py` | 从轨迹存储采集失败样本，用 `run_evolution()` 运行一次进化循环，并检查结果。 | ~30 | ~3 分钟 |

## 前提条件

```bash
pip install scrivai
export ANTHROPIC_API_KEY=your-key-here
```

## 运行示例

```bash
# Audit example
python examples/01_audit_single_doc.py

# Generation with self-revision
python examples/02_generate_with_revision.py

# Skill evolution workflow
python examples/03_evolve_skill_workflow.py
```

每个脚本将输出写入 `tests/outputs/examples/<script_name>_<timestamp>.md`。

## 使用私有网关

如果你通过网关（如 GLM 或 MiniMax）路由请求，在运行任何示例前设置以下变量：

```bash
export ANTHROPIC_BASE_URL=https://my-gateway.example.com
export ANTHROPIC_API_KEY=my-gateway-key
export SCRIVAI_DEFAULT_MODEL=glm-5.1
```

无需修改代码——Claude Agent SDK 会自动读取 `ANTHROPIC_BASE_URL`。
