# Examples (fictional)

Everything here is invented sample data: the persona "Alex Rivera", the employers Northwind and
Contoso, and every project and number. It exists for tests, demos and the small eval in `../eval/`.
Nothing here describes a real person or company.

Point the copilot at it without touching your own files:

```powershell
$env:EXP_CORPUS_DIR = "examples/corpus"
$env:EXP_PERSIST_DIR = "chroma_store_demo"
$env:EXP_PERSONA_PATH = "examples/persona.md"
$env:EXP_STYLE_PATH = "examples/style_examples.md"
python -m copilot.cli ingest
python -m copilot.cli answer "What billing pipeline did you build at Northwind?" --fast
```
