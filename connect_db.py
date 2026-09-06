"""Criação de conexões com o banco MySQL hospedado na Aiven."""

import os

import mysql.connector
from dotenv import load_dotenv


load_dotenv()


def get_db_connection():
    """Cria e retorna uma nova conexão com o MySQL da Aiven.

    As configurações sensíveis ficam no arquivo ``.env`` (ou nas variáveis de
    ambiente do serviço). A porta e o certificado possuem valores padrão para
    que possam ser omitidos quando a configuração da Aiven os utilizar.
    """
    config = {
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "host": os.getenv("DB_HOST"),
        "port": int(os.getenv("DB_PORT", 20980)),
        "database": os.getenv("DB_NAME"),
        "ssl_ca": os.getenv("DB_SSL_CA", "ca.pem"),
    }
    return mysql.connector.connect(**config)
