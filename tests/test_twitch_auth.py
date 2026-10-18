"""Ces tests vérifient l’authentification avec de faux jetons, sans contacter Twitch."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from dotenv import dotenv_values

from src.tools import twitch_auth as auth
from src.tools import twitch_chat


class TwitchAuthTests(unittest.TestCase):
    def identity(self, **overrides):
        return {"client_id": "app", "login": "lumitheboat",
                "scopes": ["chat:read", "chat:edit"], "expires_in": 300, **overrides}

    def test_rejects_streamer_wrong_app_missing_scope_and_expired_token(self):
        for changes in ({"login": "origaniretv"}, {"client_id": "other"},
                        {"scopes": ["chat:read"]}, {"expires_in": 0}):
            with self.subTest(changes=changes), patch.object(
                auth, "request_json", return_value=(200, self.identity(**changes))
            ):
                with self.assertRaises(auth.AuthError):
                    auth.validate_token("fake", "app", "LumiTheBoat")

    def test_pending_then_success_saves_only_validated_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            path.write_text("# Keep this\nOBS_WEBSOCKET_PASSWORD=unchanged\nTWITCH_OAUTH_TOKEN=old\n")
            replies = [(200, {"device_code": "private", "user_code": "ABCDEF", "expires_in": 600}),
                       (400, {"message": "authorization_pending"}),
                       (200, {"access_token": "fake-token", "refresh_token": "fake-refresh"}),
                       (200, self.identity())]
            with patch.object(auth, "request_json", side_effect=replies), \
                 patch.object(auth.time, "sleep"), patch("builtins.print") as output:
                auth.authorize("app", "LumiTheBoat", path)
            saved = dotenv_values(path)
            self.assertEqual(saved["TWITCH_OAUTH_TOKEN"], "fake-token")
            self.assertEqual(saved["TWITCH_BOT_USERNAME"], "lumitheboat")
            self.assertEqual(saved["OBS_WEBSOCKET_PASSWORD"], "unchanged")
            self.assertIn("# Keep this", path.read_text())
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertNotIn("fake-token", str(output.call_args_list))
            self.assertNotIn("fake-refresh", str(output.call_args_list))
            self.assertNotIn("private", str(output.call_args_list))

    def test_wrong_account_never_overwrites_saved_credentials(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / ".env"
            before = "TWITCH_OAUTH_TOKEN=existing\n"
            path.write_text(before)
            replies = [(200, {"device_code": "private", "user_code": "ABCDEF", "expires_in": 600}),
                       (200, {"access_token": "fake-token", "refresh_token": "fake-refresh"}),
                       (200, self.identity(login="origaniretv"))]
            with patch.object(auth, "request_json", side_effect=replies), \
                 patch.object(auth.time, "sleep"), patch("builtins.print"):
                with self.assertRaises(auth.AuthError):
                    auth.authorize("app", "LumiTheBoat", path)
            self.assertEqual(path.read_text(), before)

    def test_denial_stops_polling(self):
        replies = [(200, {"device_code": "private", "user_code": "ABCDEF", "expires_in": 600}),
                   (400, {"message": "access_denied"})]
        with patch.object(auth, "request_json", side_effect=replies), \
             patch.object(auth.time, "sleep"), patch.object(auth, "save_settings") as save, \
             patch("builtins.print"):
            with self.assertRaises(auth.AuthError):
                auth.authorize("app", "LumiTheBoat")
            save.assert_not_called()

    def test_connection_sends_credentials_only_through_tls(self):
        with patch.object(twitch_chat.socket, "create_connection") as connect, \
             patch.object(twitch_chat.ssl, "create_default_context") as context:
            raw = connect.return_value
            encrypted = context.return_value.wrap_socket.return_value
            result = twitch_chat.connect("origaniretv", "lumitheboat", "fake-token")
            self.assertIs(result, encrypted)
            raw.sendall.assert_not_called()
            context.return_value.wrap_socket.assert_called_once_with(raw, server_hostname=twitch_chat.HOST)
            encrypted.sendall.assert_called_once()


if __name__ == "__main__":
    unittest.main()
