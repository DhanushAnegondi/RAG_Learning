# RAG_Learning

Projects built to learn LLMs, agents and applied machine learning by building real things on
real data. Each folder is a self-contained project with its own README, tests and run steps.

## Projects

| Project | What it is | Main tools |
|---|---|---|
| [corrective-rag](corrective-rag/) | A retrieval pipeline that checks its own sources: it grades every retrieved chunk, and when the documents cannot answer, it rewrites the question and falls back to web search | LangGraph, NVIDIA NIM, Chroma |
| [experience-copilot](experience-copilot/) | Answers interview-style questions about your own experience, grounded in your own documents, with controls for length and tone. Reuses corrective-rag for grounding | LangGraph, corrective-rag |
| [weather-prediction](weather-prediction/) | Measures how wrong published weather forecasts are for a city, corrects them where the data proves it can, and gives every number a likely range. Includes a site and a chat assistant | Postgres, SQL, scikit-learn, LangGraph, Claude |
| [recommendation](recommendation/) | An English + Telugu movie recommender that fills missing film data instead of dropping it, and compares four recommenders on what users went on to like | DuckDB, SQL, scikit-learn |

## Where to start

- New to RAG: read `corrective-rag` first, then `experience-copilot`, which builds on it.
- Interested in data pipelines with honest evaluation: `weather-prediction` and
  `recommendation` each have a results page (`results/index.html`) showing every measured
  number, the tests behind it, and the known limits.

Each project keeps its secrets in a local `.env` file that is not in this repo; copy the
project's `.env.example` where one exists.
