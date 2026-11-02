"""Compare top-four retrieved fixture chunks without requiring a chat model."""
import json
import os
from pathlib import Path
import sys
import time
from uuid import uuid4

from dotenv import load_dotenv

root = Path(__file__).resolve().parents[1]
repo = root.parent
sys.path[:0] = [str(root / 'src'), str(repo / 'corrective-rag/src')]
load_dotenv(root / '.env')
os.chdir(root)
from copilot import engine, ingest, retrieval_v2
from copilot.evaluation import isolated_indexes

corpus = root / 'eval/fixtures/corpus'
rows = [json.loads(x) for x in (root / 'eval/questions.jsonl').read_text().splitlines()]
output = root / 'eval/results/retrieval-live.json'
output.parent.mkdir(parents=True, exist_ok=True)
results = []
with isolated_indexes(corpus, output.parent / ('retrieval-index-' + uuid4().hex[:10])):
    ingest.build_index()
    retrieval_v2.build_index()
    for row in rows:
        if not row['answerable']:
            continue
        item = {'id': row['id'], 'split': row['split'], 'expected': row['expected_sources']}
        for version in ('v1', 'v2'):
            start = time.perf_counter()
            try:
                docs = (engine.ground(row['question'], grade=False)['kept'] if version == 'v1'
                        else retrieval_v2.retrieve_candidates(row['question'])[:4])
                sources = []
                for doc in docs:
                    path = Path(doc.metadata['source'])
                    sources.append(path.resolve().relative_to(corpus).as_posix() if path.is_absolute() else path.as_posix())
                rank = next((i for i, source in enumerate(sources, 1) if source in row['expected_sources']), None)
                item[version] = {'sources': sources, 'hit': rank is not None, 'rr': 1 / rank if rank else 0,
                                 'seconds': round(time.perf_counter() - start, 3), 'error': None}
            except Exception as error:
                item[version] = {'error': type(error).__name__}
        results.append(item)
        output.write_text(json.dumps(results, indent=2), encoding='utf-8')
        print(row['id'], item['v1'], item['v2'], flush=True)
