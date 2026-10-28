"""Leitor do formato OLE Compound File Binary (CFB, [MS-CFB]), usado pelo Word 97–2003.

Lê o cabeçalho, a DIFAT, a FAT, a MiniFAT e o diretório, e devolve streams pelo
nome. Arquivos malformados levantam `ErroCFB`, nunca laços infinitos nem leitura
além do arquivo:
- toda cadeia de setores tem detecção de ciclo e no máximo tantos setores quanto
  o arquivo comporta;
- setor fora do arquivo, setor especial no meio de uma cadeia ou cadeia curta para
  o tamanho declarado são erro;
- o tamanho declarado de um stream não pode passar do tamanho do arquivo;
- a árvore do diretório é percorrida com conjunto de visitados.

Somente biblioteca padrão do Python.
"""
from __future__ import annotations

import struct

from .base import ErroFormato

MAGICO = b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"
MAXREGSECT = 0xFFFFFFFA
DIFSECT = 0xFFFFFFFC
FATSECT = 0xFFFFFFFD
ENDOFCHAIN = 0xFFFFFFFE
FREESECT = 0xFFFFFFFF
NOSTREAM = 0xFFFFFFFF

TIPO_STORAGE = 1
TIPO_STREAM = 2
TIPO_RAIZ = 5

# Arquivos maiores que isso não são lidos (o maior documento esperado tem dezenas de MB).
TAMANHO_MAXIMO = 512 * 1024 * 1024


class ErroCFB(ErroFormato):
    """Compound File malformado, truncado ou com cadeias inválidas."""


class Entrada:
    __slots__ = ("indice", "nome", "tipo", "esquerda", "direita", "filho", "inicio", "tamanho")

    def __init__(self, indice: int, nome: str, tipo: int, esquerda: int, direita: int,
                 filho: int, inicio: int, tamanho: int) -> None:
        self.indice = indice
        self.nome = nome
        self.tipo = tipo
        self.esquerda = esquerda
        self.direita = direita
        self.filho = filho
        self.inicio = inicio
        self.tamanho = tamanho


class CompoundFile:
    """Compound File em memória: `stream(nome)` devolve os bytes de um stream."""

    def __init__(self, dados: bytes) -> None:
        if len(dados) < 512 or not dados.startswith(MAGICO):
            raise ErroCFB("assinatura CFB ausente ou arquivo curto")
        if len(dados) > TAMANHO_MAXIMO:
            raise ErroCFB("arquivo CFB grande demais")
        self.dados = memoryview(dados)
        (versao_maior, ordem, deslocamento, deslocamento_mini) = struct.unpack_from("<HHHH", dados, 0x1A)
        if ordem != 0xFFFE:
            raise ErroCFB("ordem de bytes inválida")
        if (versao_maior, deslocamento) not in ((3, 9), (4, 12)):
            raise ErroCFB(f"versão/tamanho de setor não suportado ({versao_maior}, {deslocamento})")
        if deslocamento_mini != 6:
            raise ErroCFB("tamanho de minissetor inválido")
        self.versao = versao_maior
        self.setor = 1 << deslocamento
        self.minissetor = 64
        (n_fat, self.primeiro_dir, _transacao, self.corte_mini, primeiro_minifat, n_minifat,
         primeiro_difat, n_difat) = struct.unpack_from("<IIIIIIII", dados, 0x2C)
        if self.corte_mini != 4096:
            raise ErroCFB("limite do mini stream inválido")
        self.n_setores = (len(dados) - self.setor + self.setor - 1) // self.setor
        if self.n_setores <= 0:
            raise ErroCFB("arquivo sem setores")
        if n_fat > self.n_setores or n_difat > self.n_setores or n_minifat > self.n_setores:
            raise ErroCFB("contagem de setores maior que o arquivo")
        self.fat = self._ler_fat(dados, n_fat, primeiro_difat, n_difat)
        self.minifat: tuple[int, ...] = ()
        if n_minifat and primeiro_minifat != ENDOFCHAIN:
            bruto = self._ler_cadeia(primeiro_minifat, n_minifat * self.setor)
            self.minifat = struct.unpack(f"<{len(bruto) // 4}I", bruto[: len(bruto) // 4 * 4])
        self.entradas = self._ler_diretorio()
        raiz = self.entradas[0]
        if raiz.tipo != TIPO_RAIZ:
            raise ErroCFB("primeira entrada do diretório não é a raiz")
        self._mini: bytes | None = None
        self._raiz = raiz

    # ------------------------------------------------------------ setores
    def _bytes_setor(self, n: int) -> bytes:
        if n > MAXREGSECT or n >= self.n_setores:
            raise ErroCFB(f"setor {n} fora do arquivo")
        ini = (n + 1) * self.setor
        bloco = bytes(self.dados[ini:ini + self.setor])
        if len(bloco) < self.setor:
            if n != self.n_setores - 1:
                raise ErroCFB("setor truncado")
            bloco += b"\x00" * (self.setor - len(bloco))
        return bloco

    def _ler_fat(self, dados: bytes, n_fat: int, primeiro_difat: int, n_difat: int) -> tuple[int, ...]:
        setores_fat = [s for s in struct.unpack_from("<109I", dados, 0x4C)]
        por_setor = self.setor // 4
        atual = primeiro_difat
        vistos: set[int] = set()
        for _ in range(n_difat):
            if atual in (ENDOFCHAIN, FREESECT):
                break
            if atual in vistos:
                raise ErroCFB("ciclo na DIFAT")
            vistos.add(atual)
            valores = struct.unpack(f"<{por_setor}I", self._bytes_setor(atual))
            setores_fat.extend(valores[:-1])
            atual = valores[-1]
        setores_fat = [s for s in setores_fat if s <= MAXREGSECT][:n_fat]
        if len(setores_fat) < n_fat:
            raise ErroCFB("DIFAT com menos setores de FAT que o declarado")
        if len(set(setores_fat)) != len(setores_fat):
            raise ErroCFB("setor de FAT repetido")
        bruto = b"".join(self._bytes_setor(s) for s in setores_fat)
        fat = struct.unpack(f"<{len(bruto) // 4}I", bruto)
        return fat

    def _cadeia(self, inicio: int, tabela: tuple[int, ...], limite: int) -> list[int]:
        """Setores da cadeia; ErroCFB em ciclo, setor inválido ou mais de `limite` setores."""
        setores: list[int] = []
        vistos: set[int] = set()
        atual = inicio
        while atual != ENDOFCHAIN:
            if atual > MAXREGSECT or atual >= len(tabela):
                raise ErroCFB(f"setor inválido {atual:#x} na cadeia")
            if atual in vistos:
                raise ErroCFB("ciclo na cadeia de setores")
            vistos.add(atual)
            setores.append(atual)
            if len(setores) > limite:
                raise ErroCFB("cadeia maior que o arquivo")
            atual = tabela[atual]
        return setores

    def _ler_cadeia(self, inicio: int, tamanho: int | None = None) -> bytes:
        if inicio == ENDOFCHAIN:
            if tamanho:
                raise ErroCFB("cadeia vazia para stream não vazio")
            return b""
        setores = self._cadeia(inicio, self.fat, self.n_setores)
        bruto = b"".join(self._bytes_setor(s) for s in setores)
        if tamanho is not None:
            if len(bruto) < tamanho:
                raise ErroCFB("cadeia curta para o tamanho declarado")
            bruto = bruto[:tamanho]
        return bruto

    # ------------------------------------------------------------ diretório
    def _ler_diretorio(self) -> list[Entrada]:
        bruto = self._ler_cadeia(self.primeiro_dir)
        entradas: list[Entrada] = []
        for i in range(len(bruto) // 128):
            reg = bruto[i * 128:(i + 1) * 128]
            comprimento = struct.unpack_from("<H", reg, 0x40)[0]
            tipo = reg[0x42]
            esquerda, direita, filho = struct.unpack_from("<III", reg, 0x44)
            inicio = struct.unpack_from("<I", reg, 0x74)[0]
            tamanho = struct.unpack_from("<Q", reg, 0x78)[0]
            if self.versao == 3:
                tamanho &= 0xFFFFFFFF
            if tipo not in (0, TIPO_STORAGE, TIPO_STREAM, TIPO_RAIZ):
                tipo = 0
            nome = ""
            if tipo and 2 <= comprimento <= 64 and comprimento % 2 == 0:
                nome = reg[: comprimento - 2].decode("utf-16-le", "replace")
            if tipo == TIPO_STREAM and tamanho > len(self.dados):
                raise ErroCFB("tamanho declarado de stream maior que o arquivo")
            entradas.append(Entrada(i, nome, tipo, esquerda, direita, filho, inicio, tamanho))
        if not entradas:
            raise ErroCFB("diretório vazio")
        return entradas

    def filhos(self, indice: int = 0) -> dict[str, Entrada]:
        """Entradas diretamente dentro do storage `indice` (0 = raiz), por nome."""
        if not 0 <= indice < len(self.entradas):
            raise ErroCFB("índice de diretório inválido")
        resultado: dict[str, Entrada] = {}
        pendentes = [self.entradas[indice].filho]
        vistos: set[int] = set()
        while pendentes:
            i = pendentes.pop()
            if i == NOSTREAM:
                continue
            if i >= len(self.entradas) or i in vistos or i == indice:
                raise ErroCFB("árvore do diretório inválida")
            vistos.add(i)
            entrada = self.entradas[i]
            if entrada.tipo in (TIPO_STORAGE, TIPO_STREAM):
                resultado.setdefault(entrada.nome, entrada)
            pendentes.append(entrada.esquerda)
            pendentes.append(entrada.direita)
        return resultado

    # ------------------------------------------------------------ streams
    def _mini_stream(self) -> bytes:
        if self._mini is None:
            raiz = self._raiz
            if raiz.tamanho > len(self.dados):
                raise ErroCFB("mini stream maior que o arquivo")
            self._mini = self._ler_cadeia(raiz.inicio, raiz.tamanho)
        return self._mini

    def ler(self, entrada: Entrada) -> bytes:
        if entrada.tipo != TIPO_STREAM:
            raise ErroCFB(f"{entrada.nome} não é stream")
        if entrada.tamanho == 0:
            return b""
        if entrada.tamanho < self.corte_mini:
            mini = self._mini_stream()
            n_mini = len(mini) // self.minissetor
            setores = self._cadeia(entrada.inicio, self.minifat, n_mini)
            partes = []
            for s in setores:
                if s >= n_mini:
                    raise ErroCFB("minissetor fora do mini stream")
                partes.append(mini[s * self.minissetor:(s + 1) * self.minissetor])
            bruto = b"".join(partes)
            if len(bruto) < entrada.tamanho:
                raise ErroCFB("cadeia da MiniFAT curta para o tamanho declarado")
            return bruto[:entrada.tamanho]
        return self._ler_cadeia(entrada.inicio, entrada.tamanho)

    def stream(self, caminho: str) -> bytes:
        """Bytes do stream pelo caminho ("WordDocument" ou "Storage/Stream")."""
        indice = 0
        partes = caminho.split("/")
        for n, parte in enumerate(partes):
            filhos = self.filhos(indice)
            if parte not in filhos:
                raise KeyError(caminho)
            entrada = filhos[parte]
            if n == len(partes) - 1:
                return self.ler(entrada)
            if entrada.tipo != TIPO_STORAGE:
                raise KeyError(caminho)
            indice = entrada.indice
        raise KeyError(caminho)

    def existe(self, caminho: str) -> bool:
        try:
            indice = 0
            partes = caminho.split("/")
            for n, parte in enumerate(partes):
                filhos = self.filhos(indice)
                if parte not in filhos:
                    return False
                if n == len(partes) - 1:
                    return True
                indice = filhos[parte].indice
        except ErroCFB:
            return False
        return False
