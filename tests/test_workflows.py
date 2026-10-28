"""Contratos dos workflows, com leitura direcionada por recuo (sem PyYAML).

Não é um parser YAML geral: lê as chaves de mapeamento e os passos usados nestes
arquivos. Blocos de shell ficam opacos, evitando confundir comandos com YAML.
A validação completa da sintaxe cabe ao actionlint/GitHub Actions.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path


RAIZ = Path(__file__).resolve().parents[1]


def entrada(texto: str, chave: str, recuo: int) -> tuple[str, str]:
    """Retorna valor na linha e corpo até a próxima chave do mesmo nível."""
    linhas = texto.splitlines()
    padrao = re.compile(rf"^{' ' * recuo}{re.escape(chave)}:\s*(.*?)\s*$")
    for inicio, linha in enumerate(linhas):
        encontrado = padrao.fullmatch(linha)
        if not encontrado:
            continue
        fim = inicio + 1
        while fim < len(linhas):
            seguinte = linhas[fim]
            if seguinte.strip() and not seguinte.lstrip().startswith("#"):
                if len(seguinte) - len(seguinte.lstrip()) <= recuo:
                    break
            fim += 1
        return encontrado[1], "\n".join(linhas[inicio + 1:fim])
    raise AssertionError(f"Chave ausente: {chave!r}, recuo {recuo}")


def secao(texto: str, chave: str, recuo: int = 0) -> str:
    return entrada(texto, chave, recuo)[1]


def valor(texto: str, chave: str, recuo: int = 0) -> str:
    literal, corpo = entrada(texto, chave, recuo)
    if literal in (">-", ">", "|", "|-"):
        return " ".join(linha.strip() for linha in corpo.splitlines())
    if literal.startswith(('"', "'")) and literal[-1:] == literal[:1]:
        return literal[1:-1]
    return literal


def permissoes(texto: str, recuo: int) -> dict[str, str]:
    corpo = secao(texto, "permissions", recuo)
    pares = re.findall(rf"^{' ' * (recuo + 2)}([\w-]+): (\w+)$", corpo, re.MULTILINE)
    return dict(pares)


def passos(job: str) -> list[str]:
    corpo = secao(job, "steps", 4)
    inicios = [m.start() for m in re.finditer(r"^      - ", corpo, re.MULTILINE)]
    return [corpo[inicio:fim] for inicio, fim in zip(inicios, inicios[1:] + [len(corpo)])]


def passo_contendo(job: str, trecho: str) -> str:
    encontrados = [passo for passo in passos(job) if trecho in passo]
    if len(encontrados) != 1:
        raise AssertionError(f"Esperado um passo com {trecho!r}; encontrados: {len(encontrados)}")
    return encontrados[0]


class TestWorkflows(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.textos = (RAIZ / ".github/workflows/textos.yml").read_text(encoding="utf-8")
        cls.backend = (RAIZ / ".github/workflows/backend.yml").read_text(encoding="utf-8")
        cls.coleta = (RAIZ / ".github/workflows/coleta.yml").read_text(encoding="utf-8")

    def job(self, workflow: str, nome: str) -> str:
        return secao(secao(workflow, "jobs"), nome, 2)

    def test_leitor_preserva_on_e_nao_interpreta_shell(self):
        exemplo = "on:\n  pull_request:\njobs:\n  teste:\n    steps:\n      - run: |\n          on: falso\n"
        self.assertIn("pull_request:", secao(exemplo, "on"))
        self.assertEqual(valor("    if: >-\n      evento &&\n      sucesso\n    steps:\n", "if", 4),
                         "evento && sucesso")
        with self.assertRaises(AssertionError):
            secao(secao(exemplo, "jobs"), "on", 2)

    def test_textos_disparos_e_barreira_de_sucesso(self):
        eventos = secao(self.textos, "on")
        self.assertEqual(set(re.findall(r"^  ([\w_]+):", eventos, re.MULTILINE)),
                         {"workflow_run", "workflow_dispatch", "pull_request"})
        anterior = secao(eventos, "workflow_run", 2)
        self.assertEqual(valor(anterior, "workflows", 4), '["Coleta semanal"]')
        self.assertEqual(valor(anterior, "types", 4), "[completed]")
        self.assertEqual(valor(anterior, "branches", 4), "[main]")
        publicar = self.job(self.textos, "publicar")
        condicao = valor(publicar, "if", 4)
        self.assertIn("github.ref == 'refs/heads/main'", condicao)
        self.assertIn("github.event_name == 'workflow_dispatch'", condicao)
        self.assertIn("github.event.workflow_run.conclusion == 'success'", condicao)
        self.assertEqual(valor(passo_contendo(publicar, "actions/checkout@"), "ref", 10), "main")

    def test_permissoes_minimas_por_job(self):
        for workflow in (self.textos, self.backend):
            self.assertEqual(permissoes(workflow, 0), {"contents": "read"})
        self.assertEqual(permissoes(self.job(self.textos, "verificar"), 4), {"contents": "read"})
        self.assertEqual(permissoes(self.job(self.textos, "publicar"), 4),
                         {"contents": "write", "id-token": "write", "attestations": "write"})
        self.assertEqual(set(re.findall(r"^  ([\w-]+):", secao(self.textos, "jobs"), re.MULTILINE)),
                         {"verificar", "publicar"})
        self.assertEqual(set(re.findall(r"^  ([\w-]+):", secao(self.backend, "jobs"), re.MULTILINE)),
                         {"testes", "staging", "production"})
        for nome in ("testes", "staging", "production"):
            job = self.job(self.backend, nome)
            self.assertEqual(permissoes(job, 4), {"contents": "read"})
            self.assertIn("persist-credentials: false", passo_contendo(job, "actions/checkout@"))

    def test_textos_concorrencia_nao_cancela_coleta(self):
        coleta = secao(self.coleta, "concurrency")
        concorrencia = secao(self.textos, "concurrency")
        self.assertEqual(valor(coleta, "group", 2), "coleta")
        grupo = valor(concorrencia, "group", 2)
        self.assertIn("github.event_name == 'pull_request'", grupo)
        self.assertIn("format('textos-pr-{0}', github.ref)", grupo)
        self.assertIn("|| 'coleta'", grupo)
        for bloco in (coleta, concorrencia):
            self.assertEqual(valor(bloco, "cancel-in-progress", 2), "false")

    def test_textos_pr_somente_simula_e_aceita_secret_ausente(self):
        job = self.job(self.textos, "verificar")
        self.assertEqual(valor(job, "if", 4), "github.event_name == 'pull_request'")
        self.assertEqual(valor(job, "environment", 4), "pr-simulacao")
        self.assertIn("persist-credentials: false", passo_contendo(job, "actions/checkout@"))
        simulacao = passo_contendo(job, "python -m coletor.nuvem")
        self.assertIn("--ambiente staging --simular", simulacao)
        self.assertIn("secrets.CLOUDFLARE_API_TOKEN_LEITURA", simulacao)
        self.assertEqual(set(re.findall(r"secrets\.([A-Z_]+)", job)),
                         {"CLOUDFLARE_API_TOKEN_LEITURA"})
        self.assertNotIn("actions/cache", job)
        self.assertNotRegex(job, r"(?m)^\s+cache:")
        self.assertIn('[ -z "$CLOUDFLARE_API_TOKEN" ]', simulacao)
        self.assertIn('[ "$PR_REPOSITORY" != "$GITHUB_REPOSITORY" ]', simulacao)
        self.assertLess(simulacao.index("::notice::"), simulacao.index("exit 0"))
        self.assertLess(simulacao.index("exit 0"), simulacao.index("python -m coletor.nuvem"))
        for passo in passos(job):
            self.assertNotRegex(passo, r"\bgit\b[^\n]*\b(push|commit)\b")
            self.assertNotIn("--commit-textos", passo)
            self.assertNotIn("secrets.R2_", passo)
            self.assertNotIn("secrets.CLOUDFLARE_API_TOKEN_DEPLOY", passo)
        self.assertEqual(job.count("python -m coletor.nuvem"), 1)

    def test_textos_extracao_validacao_e_ordem_de_publicacao(self):
        job = self.job(self.textos, "publicar")
        self.assertIn("git worktree add -b dados-textos", job)
        extracao = passo_contendo(job, "python -m coletor.textos")
        self.assertIn("--ocr --max-arquivos 1500 --max-minutos 120 --commit-textos", extracao)
        self.assertIn('--textos "$RADAR_TEXTOS"', extracao)
        validacao = passo_contendo(job, "python -m coletor.validar")
        self.assertIn('python -m coletor.validar --textos "$RADAR_TEXTOS"', validacao)
        self.assertEqual(valor(validacao, "RADAR_COLETA", 10), "1")
        self.assertIn("python -m unittest discover -s tests -t .", validacao)
        push_textos = 'git -C "$RADAR_TEXTOS" push origin HEAD:dados-textos'
        commit_manifesto = 'git commit -m "Atualiza manifestos'
        ordem = [job.index("python -m coletor.textos"), job.index("python -m coletor.validar"),
                 job.index(push_textos), job.index("git add data/textos"), job.index(commit_manifesto),
                 job.index("git pull --rebase origin main"), job.index("git push origin HEAD:main"),
                 job.index("python -m coletor.nuvem")]
        self.assertEqual(ordem, sorted(ordem))
        self.assertIn("for tentativa in 1 2 3; do", job)
        self.assertNotIn("commit_textos", job)

    def test_textos_ferramentas_cache_e_node_antes_da_nuvem(self):
        for nome in ("verificar", "publicar"):
            job = self.job(self.textos, nome)
            self.assertEqual(valor(job, "runs-on", 4), "ubuntu-24.04")
            node = passo_contendo(job, "actions/setup-node@")
            self.assertEqual(valor(node, "node-version", 10), "22")
            npm = passo_contendo(job, "run: npm ci")
            self.assertEqual(valor(npm, "working-directory", 8), "worker")
            self.assertLess(job.index(node), job.index(npm))
            self.assertLess(job.index(npm), job.index("python -m coletor.nuvem"))
        job = self.job(self.textos, "publicar")
        ferramentas = passo_contendo(job, "apt-get install")
        self.assertRegex(ferramentas, r"apt-get install[^\n]*poppler-utils tesseract-ocr tesseract-ocr-por")
        for comando in ("pdftotext -v", "pdftoppm -v", "tesseract --version", "tesseract --list-langs"):
            self.assertIn(comando, ferramentas)
        self.assertIn("dpkg-query -W poppler-utils tesseract-ocr tesseract-ocr-por", ferramentas)
        self.assertIn("dpkg-query -L tesseract-ocr-por", ferramentas)
        self.assertIn("/por.traineddata$", ferramentas)
        self.assertIn("sha256sum", ferramentas)
        self.assertIn("RADAR_CACHE:", job)

    def test_textos_cache_so_originais_com_chave_semanal_e_reserva_em_falha(self):
        job = self.job(self.textos, "publicar")
        restaurar = passo_contendo(job, "actions/cache/restore@v4")
        salvar = passo_contendo(job, "actions/cache/save@v4")
        self.assertNotIn("actions/cache@", self.textos)
        self.assertEqual(sum("uses: actions/cache" in p for p in passos(job)), 2)
        permitidos = {
            "${{ env.RADAR_CACHE }}/arquivos/",
            "${{ env.RADAR_CACHE }}/textos_sha256.json",
            "${{ env.RADAR_CACHE }}/siscam_arquivos_sha256.json",
            "${{ env.RADAR_CACHE }}/atas_cache_sha256.json",
        }
        for passo in (restaurar, salvar):
            caminhos = secao(passo, "path", 10)
            self.assertEqual({linha.strip() for linha in caminhos.splitlines() if linha.strip()}, permitidos)
            for proibido in ("/ocr", "/texto_bruto", "/extracoes", "/textos_ementas.json"):
                self.assertNotIn(proibido, caminhos)
            self.assertIn("always()", valor(passo, "if", 8))
            chave = valor(passo, "key", 10)
            self.assertIn("originais-publicos-v1-", chave)
            self.assertIn("steps.chave-cache.outputs.semana", chave)
            self.assertNotIn("github.run_id", chave)
            self.assertNotIn("github.run_attempt", chave)
        self.assertEqual(valor(restaurar, "key", 10), valor(salvar, "key", 10))
        self.assertEqual(valor(restaurar, "restore-keys", 10),
                         "textos-${{ runner.os }}-originais-publicos-v1-")
        self.assertIn("steps.cache-originais.outputs.cache-hit != 'true'", valor(salvar, "if", 8))
        self.assertIn("date -u +%G-%V", passo_contendo(job, "id: chave-cache"))
        self.assertLess(job.index(restaurar), job.index("python -m coletor.textos"))
        self.assertLess(job.index("python -m coletor.nuvem"), job.index(salvar))

    def test_textos_npm_preserva_binarios_sem_credenciais_git_persistidas(self):
        for nome in ("verificar", "publicar"):
            job = self.job(self.textos, nome)
            self.assertEqual(valor(passo_contendo(job, "actions/checkout@"), "persist-credentials", 10),
                             "false")
            npm = passo_contendo(job, "run: npm ci")
            self.assertIn("run: npm ci", npm)
            self.assertNotIn("GH_TOKEN", npm)
            self.assertNotIn("secrets.", npm)
        job = self.job(self.textos, "publicar")
        for passo in passos(job):
            if re.search(r"\bgit\b[^\n]*\bpush\b", passo):
                self.assertEqual(valor(passo, "GH_TOKEN", 10), "${{ github.token }}")
                self.assertIn("GIT_CONFIG_KEY_0=http.https://github.com/.extraheader", passo)
                self.assertIn('"$GH_TOKEN" | base64 -w0', passo)
                self.assertNotRegex(passo, r"git config[^\n]*extraheader")
            else:
                self.assertNotIn("GH_TOKEN", passo)
                self.assertNotIn("github.token", passo)
                self.assertNotIn("secrets.GITHUB_TOKEN", passo)
        self.assertNotIn("secrets.CLOUDFLARE_API_TOKEN_DEPLOY", self.textos)

    def test_textos_atestacao_e_reserva_sem_textos_brutos(self):
        job = self.job(self.textos, "publicar")
        self.assertEqual(valor(job, "environment", 4), "production")
        sincronizar = passo_contendo(job, "python -m coletor.nuvem")
        self.assertIn('--ambiente production --exportar "$EXPORTACOES"', sincronizar)
        self.assertIn("secrets.CLOUDFLARE_API_TOKEN_DADOS", sincronizar)
        self.assertIn("vars.CLOUDFLARE_ACCOUNT_ID", sincronizar)
        self.assertIn('--commit "$(git rev-parse HEAD)"', sincronizar)
        atestar = passo_contendo(job, "actions/attest-build-provenance@")
        self.assertIn("data/textos/manifesto-*.json", atestar)
        self.assertIn(".exportacoes/**/SHA256SUMS", atestar)
        artefato = passo_contendo(job, "actions/upload-artifact@")
        self.assertEqual(valor(artefato, "if", 8), "failure()")
        self.assertEqual(valor(artefato, "retention-days", 10), "14")
        self.assertIn("data/textos/", artefato)
        self.assertNotIn(".dados-textos", artefato)
        self.assertNotIn(".radar-cache", artefato)
        restaurar = passo_contendo(job, "git restore --staged --worktree")
        self.assertEqual(valor(restaurar, "if", 8), "failure()")
        self.assertLess(job.index(artefato), job.index(restaurar))

    def test_backend_disparos_testes_e_promocao(self):
        eventos = secao(self.backend, "on")
        self.assertEqual(valor(secao(eventos, "push", 2), "branches", 4), "[main]")
        for evento in ("pull_request", "push"):
            self.assertIn('"worker/**"', secao(secao(eventos, evento, 2), "paths", 4))
        testes = self.job(self.backend, "testes")
        self.assertEqual(valor(testes, "working-directory", 8), "worker")
        self.assertIn('node-version: "22"', testes)
        self.assertLess(testes.index("npm ci"), testes.index("npm test"))
        self.assertLess(testes.index("npm test"), testes.index("npm run typecheck"))
        staging = self.job(self.backend, "staging")
        producao = self.job(self.backend, "production")
        self.assertEqual(valor(staging, "needs", 4), "testes")
        self.assertEqual(valor(producao, "needs", 4), "staging")
        for job, ambiente in ((staging, "staging"), (producao, "production")):
            self.assertEqual(valor(job, "environment", 4), ambiente)
            self.assertEqual(valor(job, "if", 4),
                             "github.event_name == 'push' && github.ref == 'refs/heads/main'")
            self.assertIn("secrets.CLOUDFLARE_API_TOKEN_DEPLOY", job)
            self.assertIn("vars.CLOUDFLARE_ACCOUNT_ID", job)
            self.assertEqual(valor(job, "working-directory", 8), "worker")
            self.assertLess(job.index("npm ci"), job.index("npx wrangler d1 migrations apply"))
            self.assertLess(job.index("npx wrangler d1 migrations apply"), job.index("npx wrangler deploy"))
        self.assertIn("npx wrangler d1 migrations apply radar-niteroi-staging --remote --env staging", staging)
        self.assertIn("npx wrangler deploy --env staging", staging)
        self.assertLess(staging.index("npx wrangler deploy"), staging.index("test/integracao.test.ts"))
        self.assertIn("npx vitest run test/integracao.test.ts", staging)
        self.assertIn("https://radar-niteroi-api-staging.tormenta.workers.dev", staging)
        for rota in ("/api/saude", "/api/busca?q=lei"):
            self.assertIn(rota, staging)
        self.assertIn("curl --fail-with-body", staging)
        self.assertIn("npx wrangler d1 migrations apply radar-niteroi --remote", producao)
        self.assertIn("COMMIT: ${{ github.sha }}", producao)
        self.assertIn('npx wrangler deploy --var "COMMIT:$COMMIT"', producao)

    def test_coleta_temas_depois_de_classificar_e_antes_de_validar(self):
        job = self.job(self.coleta, "coletar")
        classificar = passo_contendo(job, "python -m coletor.classificar")
        temas = passo_contendo(job, "python -m coletor.temas")
        self.assertEqual(valor(classificar, "timeout-minutes", 8), "75")
        self.assertEqual(valor(temas, "timeout-minutes", 8), "15")
        self.assertEqual(valor(temas, "continue-on-error", 8), "true")
        self.assertIn("python -m coletor.temas --limite 2000 --max-minutos 12", temas)
        for passo in (classificar, temas):
            self.assertIn("OPENCODE_API_KEY: ${{ secrets.OPENCODE_API_KEY }}", passo)
            self.assertIn("OPENCODE_MODEL: ${{ vars.OPENCODE_MODEL }}", passo)
            self.assertIn('if [ -z "$OPENCODE_MODEL" ]; then unset OPENCODE_MODEL; fi', passo)
        self.assertLess(job.index(classificar), job.index(temas))
        self.assertLess(job.index(temas), job.index("python -m coletor.validar"))
        self.assertEqual(valor(job, "timeout-minutes", 4), "350")


if __name__ == "__main__":
    unittest.main()
