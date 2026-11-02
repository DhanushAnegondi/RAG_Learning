from copilot.question import intent, guidance, search_question
from copilot.answer import build_prompt
import pytest


@pytest.mark.parametrize('question,expected', [
    ('What is my tech stack at Rocket?', 'stack'),
    ('Which technologies did I use?', 'stack'),
    ('Tell me about yourself', 'introduction'),
    ('Walk me through my resume', 'introduction'),
    ('Tell me about a time I managed the team and reported progress', 'experience'),
    ('What did I implement at Rocket?', 'experience'),
    ('Tell me about a time I managed the team and which tools I used', 'experience'),
    ('What tools did I use to resolve the outage?', 'experience'),
    ('How many DAGs did I build?', 'direct'),
])
def test_intent(question, expected):
    assert intent(question) == expected


def test_stack_format_overrides_paragraph_style():
    system, _ = build_prompt('What is my tech stack?', 'Python [S1]', '', '', 'medium', 'professional', cite_sources=True)
    assert 'compact list' in system and 'overrides paragraph' in system


def test_introduction_retrieval_has_work_terms():
    assert 'contributions' in search_question('Tell me about yourself')
    assert 'do not promote a technical project into team management' in guidance('Tell me about a time I managed the team')


def test_stack_is_rendered_as_categories_without_a_story(monkeypatch):
    from copilot import answer
    class Fake:
        def with_structured_output(self, schema):
            return self
        def invoke(self, messages):
            return answer.StackAnswer(groups=[answer.StackGroup(category='Languages', technologies=['Python','SQL'], source_ids=['S1'])])
    monkeypatch.setattr(answer,'chat',lambda *args:Fake())
    output=answer.generate_answer('What is my tech stack?', '[S1] Python and SQL',persona='',style='',cite_sources=True)
    assert output == '- **Languages:** Python, SQL [S1]'
