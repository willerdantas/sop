"""
Criptografia simetrica (Fernet) para segredos guardados no .env
(string de conexao dos bancos, dados do administrador padrao) e para
dados pessoais gravados no banco (telefone/e-mail).

A chave fica em ENCRYPTION_KEY (.env). Pode ser uma lista separada por
virgula ("nova,antiga"): cifra sempre com a primeira e decifra com qualquer
uma - assim uma troca de chave nao perde o que foi cifrado com a anterior.

    python3 crypto_utils.py gerar-chave
    python3 crypto_utils.py cifrar "valor em texto puro"
    python3 crypto_utils.py rotacionar-chave [.env|.env.homolog]
        gera chave nova, re-cifra os valores do arquivo com ela e troca a
        SECRET_KEY (use se o .env vazou - ex: foi parar no git).
"""
import os
import secrets
import sys

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

# Valores do .env guardados cifrados (re-cifrados pelo rotacionar-chave).
CHAVES_CIFRADAS_ENV = ("DATABASE_URL", "INTEGRA_DATABASE_URL", "ADMIN_DEFAULT_LOGIN", "ADMIN_DEFAULT_SENHA")


def _chaves():
    bruto = os.environ.get("ENCRYPTION_KEY", "")
    return [c.strip() for c in bruto.split(",") if c.strip()]


def _fernet():
    chaves = _chaves()
    if not chaves:
        raise RuntimeError(
            "ENCRYPTION_KEY nao definida no .env. Gere uma com: "
            "python3 crypto_utils.py gerar-chave"
        )
    return MultiFernet([Fernet(c.encode()) for c in chaves])


def cifrar(texto_puro):
    return _fernet().encrypt(texto_puro.encode()).decode()


def decifrar(texto_cifrado):
    """Decifra um valor. Se nao houver ENCRYPTION_KEY configurada ou o
    valor nao for um token Fernet valido (ex: ambiente antigo, ainda nao
    migrado), devolve o proprio texto sem alterar."""
    if not texto_cifrado:
        return texto_cifrado
    try:
        fernet = _fernet()
    except RuntimeError:
        return texto_cifrado
    try:
        return fernet.decrypt(texto_cifrado.encode()).decode()
    except (InvalidToken, ValueError):
        return texto_cifrado


def cifrar_campo(valor):
    """Cifra um dado pessoal antes de gravar no banco (None/"" passam direto).
    Sem ENCRYPTION_KEY, grava em texto puro (o decifrar_campo aceita os dois)."""
    if not valor:
        return valor
    try:
        return cifrar(valor)
    except RuntimeError:
        return valor


def decifrar_campo(valor):
    return decifrar(valor)


def decifrar_campos(linhas, *campos):
    """Decifra 'campos' em uma linha (dict) ou lista de linhas, no lugar."""
    if not linhas:
        return linhas
    for linha in (linhas if isinstance(linhas, list) else [linhas]):
        for campo in campos:
            if campo in linha:
                linha[campo] = decifrar_campo(linha[campo])
    return linhas


def rotacionar_chave(caminho_env):
    """Gera ENCRYPTION_KEY nova, re-cifra os valores do .env com ela (a antiga
    continua na lista para decifrar dados ja gravados no banco) e gera uma
    SECRET_KEY nova (derruba as sessoes abertas). Nao imprime segredos."""
    from dotenv import dotenv_values, set_key

    valores = dotenv_values(caminho_env)
    antigas = [c.strip() for c in (valores.get("ENCRYPTION_KEY") or "").split(",") if c.strip()]
    os.environ["ENCRYPTION_KEY"] = ",".join(antigas)
    texto_puro = {chave: decifrar(valores[chave]) for chave in CHAVES_CIFRADAS_ENV if valores.get(chave)}

    nova = Fernet.generate_key().decode()
    os.environ["ENCRYPTION_KEY"] = ",".join([nova] + antigas)
    set_key(caminho_env, "ENCRYPTION_KEY", os.environ["ENCRYPTION_KEY"], quote_mode="never")
    for chave, valor in texto_puro.items():
        set_key(caminho_env, chave, cifrar(valor), quote_mode="never")
    set_key(caminho_env, "SECRET_KEY", secrets.token_hex(32), quote_mode="never")
    return sorted(texto_puro)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 crypto_utils.py gerar-chave | cifrar <valor> | decifrar <valor> | rotacionar-chave [arquivo .env]")
        sys.exit(1)

    comando = sys.argv[1]
    if comando == "gerar-chave":
        print(Fernet.generate_key().decode())
    elif comando == "cifrar":
        from dotenv import load_dotenv
        load_dotenv()
        print(cifrar(sys.argv[2]))
    elif comando == "decifrar":
        from dotenv import load_dotenv
        load_dotenv()
        print(decifrar(sys.argv[2]))
    elif comando == "rotacionar-chave":
        arquivo = sys.argv[2] if len(sys.argv) > 2 else ".env"
        recifrados = rotacionar_chave(arquivo)
        print(f"{arquivo}: ENCRYPTION_KEY e SECRET_KEY novas; re-cifrados: {', '.join(recifrados) or 'nenhum'}.")
        print("Reinicie a aplicacao. Troque tambem as SENHAS DOS BANCOS (a chave antiga vazou junto).")
    else:
        print(f"Comando desconhecido: {comando}")
        sys.exit(1)
