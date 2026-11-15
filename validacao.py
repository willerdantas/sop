"""
Validacao das entradas recebidas pela API (corpo JSON e query string).

Cada funcao devolve o valor ja convertido/normalizado ou levanta
EntradaInvalida, que vira uma resposta 400 {"erro": "..."} (ver
seguranca.py). Assim nenhum valor chega ao banco sem tipo, tamanho e
formato conferidos - alem das consultas parametrizadas, que impedem SQL
injection independentemente do conteudo.
"""
import re
from datetime import date

from flask import request


class EntradaInvalida(ValueError):
    """Entrada do usuario fora do formato esperado (mensagem vai para o cliente)."""


# Caracteres de controle (exceto tab e quebra de linha) nao tem uso legitimo
# em texto digitado e costumam aparecer em tentativas de injecao.
_CONTROLE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_LOGIN = re.compile(r"^[A-Za-z0-9._@-]+$")


def corpo_json():
    """Corpo da requisicao como dict (400 se nao for um objeto JSON)."""
    dados = request.get_json(silent=True)
    if not isinstance(dados, dict):
        raise EntradaInvalida("o corpo da requisicao deve ser um objeto JSON")
    return dados


def _vazio(valor):
    return valor is None or (isinstance(valor, str) and valor.strip() == "")


def texto(valor, rotulo, maximo, obrigatorio=False, padrao=None, multilinha=False):
    if _vazio(valor):
        if obrigatorio:
            raise EntradaInvalida(f"{rotulo} e obrigatorio")
        return padrao
    if not isinstance(valor, str):
        raise EntradaInvalida(f"{rotulo} invalido")
    valor = valor.strip()
    if len(valor) > maximo:
        raise EntradaInvalida(f"{rotulo} deve ter no maximo {maximo} caracteres")
    if _CONTROLE.search(valor) or (not multilinha and ("\n" in valor or "\r" in valor)):
        raise EntradaInvalida(f"{rotulo} contem caracteres invalidos")
    return valor


def inteiro(valor, rotulo, obrigatorio=False, minimo=None, maximo=None, padrao=None):
    if _vazio(valor):
        if obrigatorio:
            raise EntradaInvalida(f"{rotulo} e obrigatorio")
        return padrao
    if isinstance(valor, bool) or (isinstance(valor, float) and not valor.is_integer()):
        raise EntradaInvalida(f"{rotulo} deve ser um numero inteiro")
    try:
        numero = int(valor) if isinstance(valor, (int, float)) else int(str(valor).strip())
    except ValueError:
        raise EntradaInvalida(f"{rotulo} deve ser um numero inteiro") from None
    if minimo is not None and numero < minimo:
        raise EntradaInvalida(f"{rotulo} deve ser no minimo {minimo}")
    if maximo is not None and numero > maximo:
        raise EntradaInvalida(f"{rotulo} deve ser no maximo {maximo}")
    return numero


def escolha(valor, rotulo, opcoes, obrigatorio=False, padrao=None):
    if _vazio(valor):
        if obrigatorio:
            raise EntradaInvalida(f"{rotulo} e obrigatorio")
        return padrao
    if valor not in opcoes:
        raise EntradaInvalida(f"{rotulo} invalido")
    return valor


def booleano(valor, rotulo, padrao):
    if valor is None:
        return padrao
    if isinstance(valor, bool):
        return valor
    if valor in (1, "1", "true", "on"):
        return True
    if valor in (0, "0", "false", "off", ""):
        return False
    raise EntradaInvalida(f"{rotulo} invalido")


def data_iso(valor, rotulo, obrigatorio=False):
    """Data no formato AAAA-MM-DD (devolve date)."""
    if _vazio(valor):
        if obrigatorio:
            raise EntradaInvalida(f"{rotulo} e obrigatoria")
        return None
    try:
        return date.fromisoformat(str(valor).strip()[:10])
    except ValueError:
        raise EntradaInvalida(f"{rotulo} invalida (use AAAA-MM-DD)") from None


def email(valor, rotulo="e-mail"):
    valor = texto(valor, rotulo, 150)
    if valor and not _EMAIL.match(valor):
        raise EntradaInvalida(f"{rotulo} invalido")
    return valor


def login(valor):
    valor = texto(valor, "login", 60, obrigatorio=True)
    if not _LOGIN.match(valor):
        raise EntradaInvalida("login deve ter apenas letras, numeros, ponto, hifen, _ ou @")
    return valor


def senha(valor, obrigatoria=True, minimo=8):
    if _vazio(valor):
        if obrigatoria:
            raise EntradaInvalida("senha e obrigatoria")
        return None
    if not isinstance(valor, str):
        raise EntradaInvalida("senha invalida")
    if len(valor) < minimo:
        raise EntradaInvalida(f"a senha deve ter pelo menos {minimo} caracteres")
    if len(valor) > 128:
        raise EntradaInvalida("a senha deve ter no maximo 128 caracteres")
    return valor


def lista_inteiros(valor, rotulo, maximo_itens=200):
    if valor is None or valor == "":
        return []
    if not isinstance(valor, list) or len(valor) > maximo_itens:
        raise EntradaInvalida(f"{rotulo} invalido")
    return sorted({inteiro(v, rotulo) for v in valor if not _vazio(v)})


def lista_textos(valor, rotulo, opcoes, maximo_itens=50):
    """Lista de valores, mantendo apenas os presentes em 'opcoes'."""
    if valor is None:
        return []
    if not isinstance(valor, list) or len(valor) > maximo_itens:
        raise EntradaInvalida(f"{rotulo} invalido")
    return list(dict.fromkeys(v for v in valor if isinstance(v, str) and v in opcoes))


def termo_busca(valor, maximo=100):
    """Texto de busca para ILIKE, com %, _ e \\ escapados (sao curingas)."""
    valor = texto(valor, "busca", maximo)
    if not valor:
        return None
    return valor.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
