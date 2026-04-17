# M1 E2E fixtures

本目录 fixture 服务于 `tests/integration/test_m1_end_to_end.py`,串联 ExtractorPES → AuditorPES → GeneratorPES 的真 SDK 集成测试。

| 文件 | 生成方式 | 用途 |
|---|---|---|
| `substation_guide.md` | 手写合成 | ExtractorPES 抽取对象 + AuditorPES 审核对象 |
| `checkpoints_golden.json` | 手写合成 | AuditorPES 的 `data/checkpoints.json` 源(10 条) |
| `workpaper_template.docx` | `scripts/make_workpaper_template.py` | GeneratorPES 模板(3 占位符) |

## 重新生成 workpaper_template.docx

```bash
rm tests/fixtures/m1_e2e/workpaper_template.docx
conda run -n scrivai python scripts/make_workpaper_template.py
```

`substation_guide.md` 和 `checkpoints_golden.json` 是手写文本,直接编辑即可。

## 占位符契约

`workpaper_template.docx` 含 3 个 docxtpl 简单占位符(不含 Jinja 复杂标签):

| 占位符 | 期望内容 |
|---|---|
| `{{ project_name }}` | 项目名称(如"XX 220kV 变电站大修") |
| `{{ audit_summary }}` | AuditorPES 产出的总结文本(~200 字) |
| `{{ report_date }}` | 报告日期(`YYYY-MM-DD`) |

三者都是简单标识符,被 `DocxRenderer.list_placeholders()` 的正则 `[a-zA-Z_][a-zA-Z0-9_]*` 识别。
