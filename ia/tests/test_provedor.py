"""Cliente HTTP do provedor (formato OpenAI/Gemini) contra um servidor falso local."""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

from django.test import SimpleTestCase

from ia import provedores
from ia.config import Perfil

PEDIDOS = []


class Falso(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        corpo = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        PEDIDOS.append({"corpo": corpo, "auth": self.headers.get("Authorization"), "path": self.path})
        if "reasoning_effort" in corpo and corpo["model"] == "sem-raciocinio":
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b'{"error": {"message": "reasoning_effort not supported"}}')
            return
        resp = {"choices": [{"message": {"content": "<p>ok</p>"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 3}}
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(resp).encode())


class ProvedorTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.srv = HTTPServer(("127.0.0.1", 0), Falso)
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()
        super().tearDownClass()

    def perfil(self, modelo="gemini-3.8-flash"):
        return Perfil(nome="assistente", ativo=True, provedor="gemini", modelo=modelo,
                      base_url=f"http://127.0.0.1:{self.srv.server_port}/v1beta/openai", chave="CHAVE",
                      temperatura=0.3, max_tokens=100, timeout=5, prompt="", preco_entrada=0, preco_saida=0,
                      moeda="USD", extras={"parametros_extras": {"reasoning_effort": "low"}})

    def test_formato_do_pedido_e_da_resposta(self):
        PEDIDOS.clear()
        r = provedores.chamar(self.perfil(), [{"role": "user", "content": "oi"}])
        self.assertEqual(r.texto, "<p>ok</p>")
        self.assertEqual((r.tokens_entrada, r.tokens_saida), (12, 3))
        p = PEDIDOS[0]
        self.assertEqual(p["path"], "/v1beta/openai/chat/completions")
        self.assertEqual(p["auth"], "Bearer CHAVE")
        self.assertEqual(p["corpo"]["model"], "gemini-3.8-flash")
        self.assertEqual(p["corpo"]["reasoning_effort"], "low")

    def test_repete_sem_parametro_extra_recusado(self):
        PEDIDOS.clear()
        r = provedores.chamar(self.perfil("sem-raciocinio"), [{"role": "user", "content": "oi"}])
        self.assertEqual(r.texto, "<p>ok</p>")
        self.assertEqual(len(PEDIDOS), 2)
        self.assertNotIn("reasoning_effort", PEDIDOS[1]["corpo"])

    def test_sem_chave(self):
        p = self.perfil()
        p.chave = ""
        with self.assertRaises(provedores.ErroIA):
            provedores.chamar(p, [{"role": "user", "content": "oi"}])
