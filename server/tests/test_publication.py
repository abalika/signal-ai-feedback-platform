import pytest

from scripts.check_publication import inspect_file


@pytest.mark.parametrize(('path', 'content', 'expected'), [
    ('server/.env', b'CONFIG=value', 'excluded_local_file'),
    ('data/feedback.db', b'\0SQLite', 'excluded_local_file'),
    ('docs/notes.md', ('sk-' + 'a' * 24).encode(), 'credential'),
    ('docs/notes.md', ('ghp_' + 'a' * 30).encode(), 'credential'),
    ('docs/notes.md', ('D:' + '\\' + 'private/project').encode(), 'absolute_machine_path'),
    ('docs/notes.md', ('/home' + '/private/project').encode(), 'private_home_path'),
    ('docs/notes.md', ('person' + '@' + 'mail.invalid').encode(), 'personal_email'),
    ('docs/notes.md', ('138' + '00138000').encode(), 'phone_number'),
])
def test_publication_rejects_private_files_and_content(path, content, expected):
    assert expected in inspect_file(path, content)


def test_publication_accepts_example_config_urls_and_public_identity():
    content = b'OPENAI_API_KEY=<your-api-key>\nhttps://api.example.com/v1\nuser@users.noreply.github.com\n'
    assert inspect_file('server/.env.example', content) == []
    assert inspect_file('docs/demo.png', b'\0PNG') == []
