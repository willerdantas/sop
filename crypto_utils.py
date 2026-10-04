"""
Criptografia simetrica (Fernet) para segredos guardados no .env:
string de conexao dos bancos e dados do usuario administrador padrao.

A chave fica em ENCRYPTION_KEY (.env). Gere uma nova com:
    python3 crypto_utils.py gerar-chave

Para cifrar um valor (ex: ao trocar a senha do banco ou do admin):
    python3 crypto_utils.py cifrar "valor em texto puro"
"""
import os
import sys

from cryptography.fernet import Fernet, InvalidToken


def _fernet():
    chave = os.environ.get("ENCRYPTION_KEY")
    if not chave:
        raise RuntimeError(
            "ENCRYPTION_KEY nao definida no .env. Gere uma com: "
            "python3 crypto_utils.py gerar-chave"
        )
    return Fernet(chave.encode())


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


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python3 crypto_utils.py gerar-chave | cifrar <valor> | decifrar <valor>")
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
    else:
        print(f"Comando desconhecido: {comando}")
        sys.exit(1)
