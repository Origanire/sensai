# Ces tests vérifient le client MCP, le serveur Sensai et les appels d’outils avec un modèle simulé.

import unittest

from src.mcp.client import MCPClient
from src.mcp.tools import chat_with_tools, looks_like_tool_call
from tests.fakes import FakeClient


class FakeRegistry:
    """On prépare un outil en lecture seule et un autre qui modifie des données."""

    max_steps = 3

    def __init__(self):
        self.tools = {"lire": ("test", {}), "ecrire": ("test", {})}
        self.calls = []

    def ollama_tools(self):
        return [{"type": "function", "function": {"name": name}} for name in self.tools]

    def needs_confirmation(self, name):
        return name == "ecrire"

    def call(self, name, arguments):
        self.calls.append((name, arguments))
        return f"résultat de {name}"


class ServerTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = MCPClient("sensai-test", "python", ["-m", "src.mcp.server"])

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_handshake_and_tool_list(self):
        self.assertEqual(self.client.server_info["name"], "sensai")
        names = {tool["name"] for tool in self.client.list_tools()}
        self.assertTrue({"get_viewer_profile", "search_channel_docs", "add_stream_event"} <= names)

    def test_unknown_tool_is_an_error_result(self):
        text, is_error = self.client.call_tool("nope", {})
        self.assertTrue(is_error)
        self.assertIn("inconnu", text)


class ToolLoopTest(unittest.TestCase):
    def test_tool_result_is_given_back_to_the_model(self):
        client = FakeClient(tool_calls=[[{"name": "lire", "arguments": {"q": 1}}]],
                            texts=["réponse finale"])
        registry = FakeRegistry()
        messages = [{"role": "user", "content": "question"}]
        answer = chat_with_tools(client, messages, registry, confirm=lambda *_: True)

        self.assertEqual(answer, "réponse finale")
        self.assertEqual(registry.calls, [("lire", {"q": 1})])
        self.assertEqual(messages[-1], {"role": "tool", "content": "résultat de lire",
                                        "tool_name": "lire"})
        self.assertEqual(client.requests[-1][-1]["role"], "tool")

    def test_refused_write_is_not_executed(self):
        client = FakeClient(tool_calls=[[{"name": "ecrire", "arguments": {}}]], texts=["ok"])
        registry = FakeRegistry()
        messages = [{"role": "user", "content": "note ça"}]
        chat_with_tools(client, messages, registry, confirm=lambda *_: False)
        self.assertEqual(registry.calls, [])
        self.assertIn("refusé", messages[-1]["content"])

    def test_read_only_tool_needs_no_confirmation(self):
        def refuse(*_):
            raise AssertionError("confirmation demandée pour un outil en lecture")
        client = FakeClient(tool_calls=[[{"name": "lire", "arguments": {}}]], texts=["ok"])
        chat_with_tools(client, [{"role": "user", "content": "x"}], FakeRegistry(), confirm=refuse)

    def test_tool_call_written_as_text_is_detected(self):
        self.assertTrue(looks_like_tool_call('{"name": "multiply", "parameters": {"a": 1}}'))
        self.assertFalse(looks_like_tool_call("12 × 7 = 84"))


if __name__ == "__main__":
    unittest.main()
