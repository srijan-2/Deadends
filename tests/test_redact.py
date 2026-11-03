import unittest

from deadends.redact import redact

# Fake credentials are assembled at runtime so secret scanners don't flag this repo.
AWS = "AKIA" + "IOSFODNN7EXAMPLE"
GH = "ghp_" + "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6q7R8"
SLACK = "xoxb-" + "1234567890-abcdefghijkl"
ANTHROPIC = "sk-ant-" + "api03-abcdefghijklmnopqrstuvwx"
JWT = "eyJhbGciOiJIUzI1NiJ9" + "." + "eyJzdWIiOiIxMjM0NTY3ODkwIn0" + "." + "dBjftJeZ4CVPmB92K27uhbUJU1p1r"


class RedactTests(unittest.TestCase):
    def check(self, raw, kind, leaked):
        out, kinds = redact(raw)
        self.assertIn(kind, kinds)
        self.assertNotIn(leaked, out)
        self.assertIn("[REDACTED", out)

    def test_known_token_formats(self):
        self.check("key=%s in env" % AWS, "aws_access_key", AWS)
        self.check("push failed using %s" % GH, "github_token", GH)
        self.check("SLACK %s" % SLACK, "slack_token", SLACK)
        self.check("using %s" % ANTHROPIC, "anthropic_key", ANTHROPIC)
        self.check("jwt=%s" % JWT, "jwt", JWT)

    def test_bearer_header(self):
        out, kinds = redact("Authorization: Bearer abcdef0123456789abcdef0123456789")
        self.assertIn("bearer", kinds)
        self.assertNotIn("abcdef0123456789abcdef0123456789", out)

    def test_url_credentials(self):
        out, kinds = redact("could not connect to postgres://admin:s3cretPass@db.internal:5432/app")
        self.assertIn("url_credentials", kinds)
        self.assertNotIn("s3cretPass", out)
        self.assertNotIn("admin", out)
        self.assertIn("db.internal", out)  # host stays: it is useful context

    def test_private_key_block(self):
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEabc123\nxyz\n-----END RSA PRIVATE KEY-----"
        out, kinds = redact("failed:\n%s\n" % pem)
        self.assertIn("private_key", kinds)
        self.assertNotIn("MIIEabc123", out)

    def test_key_value_assignments(self):
        out, kinds = redact("DB_PASSWORD=hunter2hunter2 API_KEY='abc123xyz' client_secret: x9y8z7w6v5")
        self.assertIn("secret_assignment", kinds)
        for leaked in ("hunter2hunter2", "abc123xyz", "x9y8z7w6v5"):
            self.assertNotIn(leaked, out.replace("[REDACTED:secret]", ""))

    def test_prose_is_not_mangled(self):
        for text in (
            "invalid token: expired",
            "password must be at least 8 characters",
            "auth: failed",
            "ModuleNotFoundError: No module named 'requests'",
            "TypeError: Cannot read properties of undefined (reading 'map')",
        ):
            out, kinds = redact(text)
            self.assertEqual(out, text, text)
            self.assertEqual(kinds, [])

    def test_empty_and_idempotent(self):
        self.assertEqual(redact(""), ("", []))
        once, _ = redact("TOKEN=abc123def456ghi")
        twice, _ = redact(once)
        self.assertEqual(once, twice)


if __name__ == "__main__":
    unittest.main()
