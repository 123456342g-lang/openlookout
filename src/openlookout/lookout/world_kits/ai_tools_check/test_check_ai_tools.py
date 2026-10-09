"""用本地假服务器模拟不同版本，验证判定逻辑。python -m unittest test_check_ai_tools -v"""
import json, threading, unittest, io, contextlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import check_ai_tools as C

def serve(payloads):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            body = payloads.get(self.path)
            if body is None: self.send_response(404); self.end_headers(); return
            b = json.dumps(body).encode(); self.send_response(200); self.send_header("Content-Type", "application/json"); self.end_headers(); self.wfile.write(b)
        def log_message(self, *a): pass
    s = HTTPServer(("127.0.0.1", 0), H); threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, f"http://127.0.0.1:{s.server_address[1]}"

class T(unittest.TestCase):
    def test_ranges(self):
        self.assertTrue(C.in_range("1.9.0", ">= 1.7.0, <= 1.9.0")); self.assertFalse(C.in_range("1.9.1", ">= 1.7.0, <= 1.9.0"))
        self.assertTrue(C.in_range("1.10.2", "< 1.10.3")); self.assertFalse(C.in_range("1.12.5", "< 1.10.3"))
        self.assertTrue(C.in_range("0.35.0", ">= 0.34.2, <= 0.35.0")); self.assertFalse(C.in_range("0.40.1", ">= 0.34.2, <= 0.35.0"))
    def run_case(self, lf, ol):
        servers = []
        args = []
        if lf:
            s, u = serve({"/api/v1/version": {"version": lf, "main_version": lf, "package": "Langflow"}}); servers.append(s); args += ["--langflow-url", u]
        else:
            args += ["--langflow-url", "http://127.0.0.1:9"]
        if ol:
            s, u = serve({"/api/version": {"version": ol}}); servers.append(s); args += ["--ollama-url", u]
        else:
            args += ["--ollama-url", "http://127.0.0.1:9"]
        f = io.StringIO()
        with contextlib.redirect_stdout(f): rc = C.main(args + ["--json"])
        for s in servers: s.shutdown()
        return rc, json.loads(f.getvalue())
    def test_old_versions_flagged(self):
        rc, rep = self.run_case("1.9.0", "0.1.45")
        self.assertEqual(rc, 1)
        self.assertEqual(rep[0]["verdict"], "需要升级"); self.assertTrue(len(rep[0]["advisories"]) >= 5)
        self.assertIn("受影响范围", rep[1]["verdict"])
    def test_current_versions_clean(self):
        rc, rep = self.run_case("1.12.5", "0.1.47")
        self.assertEqual(rep[0]["advisories"], []); self.assertIn("不低于", rep[1]["verdict"])
    def test_min_fixed(self):
        rc, rep = self.run_case("1.10.2", None)
        self.assertEqual(rep[0]["min_fixed"], "1.10.3")

if __name__ == "__main__":
    unittest.main()
