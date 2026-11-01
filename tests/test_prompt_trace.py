from unittest.mock import Mock, patch
from src.core.ollama_client import OllamaClient


def test_trace_is_exact_payload_and_independent_of_later_mutations():
    client = OllamaClient({'model': 'test', 'ollama_url': 'http://localhost:11434', 'think': False})
    payload = {'model': 'test', 'messages': [{'role': 'user', 'content': 'bonjour'}], 'stream': False}
    with patch('src.core.ollama_client.requests.post', return_value=Mock()) as post:
        client.capture_requests = True
        client._post_chat(payload, stream=False)
        assert client.sent_requests == [post.call_args.kwargs['json']]
        assert client.sent_requests[0]['think'] is False
    payload['messages'][0]['content'] = 'modified'
    assert client.sent_requests[0]['messages'][0]['content'] == 'bonjour'


def test_live_calls_are_not_traced_by_default():
    client = OllamaClient({'model': 'test', 'ollama_url': 'http://localhost:11434'})
    with patch('src.core.ollama_client.requests.post', return_value=Mock()):
        client._post_chat({'messages': []}, stream=False)
    assert client.sent_requests == []
