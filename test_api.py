"""Testes de comportamento para ``api.py`` e ``connect_db.py``.

Fluxo de TDD sugerido:
    1. Execute os testes e observe os que falham (red).
    2. Faça a menor alteração em produção para torná-los verdes (green).
    3. Refatore sem alterar o comportamento coberto (refactor).

Execução:
    pytest -q
"""

from unittest.mock import MagicMock, patch

import mysql.connector
import pytest

import api
from connect_db import get_db_connection


CAMPOS_OBRIGATORIOS = (
    "logradouro",
    "tipo_logradouro",
    "bairro",
    "cidade",
    "cep",
    "tipo",
    "valor",
    "data_aquisicao",
)

IMOVEL_VALIDO = {
    "logradouro": "Rua das Flores",
    "tipo_logradouro": "Rua",
    "bairro": "Centro",
    "cidade": "São Paulo",
    "cep": "45896",
    "tipo": "apartamento",
    "valor": 350000.00,
    "data_aquisicao": "2024-01-15",
}

IMOVEL_SALVO = {"id": 1, **IMOVEL_VALIDO}


@pytest.fixture
def client():
    """Cliente HTTP do Flask, sem iniciar um servidor real."""
    api.app.config.update(TESTING=True)
    with api.app.test_client() as test_client:
        yield test_client


@pytest.fixture
def banco_mock():
    """Substitui a conexão Aiven por objetos controlados pelo teste."""
    conexao = MagicMock(name="conexao")
    cursor = MagicMock(name="cursor")
    conexao.cursor.return_value = cursor
    conexao.is_connected.return_value = True

    with patch.object(api, "get_db_connection", return_value=conexao) as obter_conexao:
        yield obter_conexao, conexao, cursor


def assert_recursos_fechados(conexao, cursor):
    """Confere que cada requisição liberou cursor e conexão."""
    cursor.close.assert_called_once_with()
    conexao.close.assert_called_once_with()


# ---------- connect_db.py ----------

def test_get_db_connection_monta_configuracao_com_variaveis_de_ambiente(monkeypatch):
    conexao_esperada = MagicMock(name="conexao_mysql")
    monkeypatch.setenv("DB_USER", "usuario_teste")
    monkeypatch.setenv("DB_PASSWORD", "senha_teste")
    monkeypatch.setenv("DB_HOST", "mysql.example.com")
    monkeypatch.setenv("DB_PORT", "3307")
    monkeypatch.setenv("DB_NAME", "imobiliaria")
    monkeypatch.setenv("DB_SSL_CA", "certificados/ca.pem")

    with patch(
        "connect_db.mysql.connector.connect", return_value=conexao_esperada
    ) as connect:
        resultado = get_db_connection()

    assert resultado is conexao_esperada
    connect.assert_called_once_with(
        user="usuario_teste",
        password="senha_teste",
        host="mysql.example.com",
        port=3307,
        database="imobiliaria",
        ssl_ca="certificados/ca.pem",
    )


def test_get_db_connection_usa_porta_e_certificado_padrao(monkeypatch):
    monkeypatch.setenv("DB_USER", "usuario_teste")
    monkeypatch.setenv("DB_PASSWORD", "senha_teste")
    monkeypatch.setenv("DB_HOST", "mysql.example.com")
    monkeypatch.setenv("DB_NAME", "imobiliaria")
    monkeypatch.delenv("DB_PORT", raising=False)
    monkeypatch.delenv("DB_SSL_CA", raising=False)

    with patch("connect_db.mysql.connector.connect") as connect:
        get_db_connection()

    assert connect.call_args.kwargs["port"] == 20980
    assert connect.call_args.kwargs["ssl_ca"] == "ca.pem"


# ---------- GET /imoveis e GET /imoveis/<id> ----------

def test_listar_imoveis_retorna_todos_os_registros(client, banco_mock):
    _, conexao, cursor = banco_mock
    cursor.fetchall.return_value = [IMOVEL_SALVO]

    resposta = client.get("/imoveis")

    assert resposta.status_code == 200
    assert resposta.get_json() == [IMOVEL_SALVO]
    conexao.cursor.assert_called_once_with(dictionary=True)
    cursor.execute.assert_called_once_with("SELECT * FROM imoveis;")
    assert_recursos_fechados(conexao, cursor)


def test_listar_imoveis_retorna_500_quando_o_banco_falha(client):
    erro = mysql.connector.Error("Aiven indisponível")
    with patch.object(api, "get_db_connection", side_effect=erro):
        resposta = client.get("/imoveis")

    assert resposta.status_code == 500
    assert "erro" in resposta.get_json()


def test_obter_imovel_retorna_registro_quando_ele_existe(client, banco_mock):
    _, conexao, cursor = banco_mock
    cursor.fetchone.return_value = IMOVEL_SALVO

    resposta = client.get("/imoveis/1")

    assert resposta.status_code == 200
    assert resposta.get_json() == IMOVEL_SALVO
    cursor.execute.assert_called_once_with(
        "SELECT * FROM imoveis WHERE id = %s;", (1,)
    )
    assert_recursos_fechados(conexao, cursor)


def test_obter_imovel_retorna_404_quando_ele_nao_existe(client, banco_mock):
    _, conexao, cursor = banco_mock
    cursor.fetchone.return_value = None

    resposta = client.get("/imoveis/999")

    assert resposta.status_code == 404
    assert resposta.get_json() == {"erro": "Imóvel não encontrado"}
    assert_recursos_fechados(conexao, cursor)


# ---------- POST /imoveis ----------

def test_adicionar_imovel_insere_dados_e_retorna_201(client, banco_mock):
    _, conexao, cursor = banco_mock
    cursor.lastrowid = 12

    resposta = client.post("/imoveis", json=IMOVEL_VALIDO)

    assert resposta.status_code == 201
    assert resposta.get_json() == {"id": 12}
    conexao.cursor.assert_called_once_with(dictionary=True)
    sql, parametros = cursor.execute.call_args.args
    assert "INSERT INTO imoveis" in sql
    assert parametros == tuple(IMOVEL_VALIDO[campo] for campo in CAMPOS_OBRIGATORIOS)
    conexao.commit.assert_called_once_with()
    assert_recursos_fechados(conexao, cursor)


def test_adicionar_imovel_rejeita_campos_obrigatorios_sem_conectar_ao_banco(client):
    dados_incompletos = IMOVEL_VALIDO.copy()
    dados_incompletos.pop("cep")

    with patch.object(api, "get_db_connection") as obter_conexao:
        resposta = client.post("/imoveis", json=dados_incompletos)

    assert resposta.status_code == 400
    assert "erro" in resposta.get_json()
    obter_conexao.assert_not_called()


def test_adicionar_imovel_rejeita_json_invalido_sem_conectar_ao_banco(client):
    with patch.object(api, "get_db_connection") as obter_conexao:
        resposta = client.post(
            "/imoveis", data="{", content_type="application/json"
        )

    assert resposta.status_code == 400
    assert resposta.is_json
    assert "erro" in resposta.get_json()
    obter_conexao.assert_not_called()


# ---------- PUT e DELETE /imoveis/<id> ----------

def test_atualizar_imovel_altera_registro_existente(client, banco_mock):
    _, conexao, cursor = banco_mock
    cursor.rowcount = 1
    dados_atualizados = {**IMOVEL_VALIDO, "valor": 410000.00}

    resposta = client.put("/imoveis/1", json=dados_atualizados)

    assert resposta.status_code == 200
    assert resposta.get_json() == {"mensagem": "Imóvel atualizado com sucesso"}
    sql, parametros = cursor.execute.call_args.args
    assert "UPDATE imoveis SET" in sql
    assert parametros == (
        *(dados_atualizados[campo] for campo in CAMPOS_OBRIGATORIOS),
        1,
    )
    conexao.commit.assert_called_once_with()
    assert_recursos_fechados(conexao, cursor)


def test_atualizar_imovel_rejeita_campos_obrigatorios_sem_conectar_ao_banco(client):
    dados_incompletos = IMOVEL_VALIDO.copy()
    dados_incompletos.pop("cidade")

    with patch.object(api, "get_db_connection") as obter_conexao:
        resposta = client.put("/imoveis/1", json=dados_incompletos)

    assert resposta.status_code == 400
    assert "erro" in resposta.get_json()
    obter_conexao.assert_not_called()


def test_atualizar_imovel_retorna_404_quando_id_nao_existe(client, banco_mock):
    _, conexao, cursor = banco_mock
    cursor.rowcount = 0

    resposta = client.put("/imoveis/999", json=IMOVEL_VALIDO)

    assert resposta.status_code == 404
    assert resposta.get_json() == {"erro": "Imóvel não encontrado"}
    conexao.commit.assert_called_once_with()
    assert_recursos_fechados(conexao, cursor)


def test_deletar_imovel_exclui_registro_existente(client, banco_mock):
    _, conexao, cursor = banco_mock
    cursor.rowcount = 1

    resposta = client.delete("/imoveis/1")

    assert resposta.status_code == 200
    assert resposta.get_json() == {"mensagem": "Imóvel excluído com sucesso"}
    cursor.execute.assert_called_once_with("DELETE FROM imoveis WHERE id = %s;", (1,))
    conexao.commit.assert_called_once_with()
    assert_recursos_fechados(conexao, cursor)


def test_deletar_imovel_retorna_404_quando_id_nao_existe(client, banco_mock):
    _, conexao, cursor = banco_mock
    cursor.rowcount = 0

    resposta = client.delete("/imoveis/999")

    assert resposta.status_code == 404
    assert resposta.get_json() == {"erro": "Imóvel não encontrado"}
    assert_recursos_fechados(conexao, cursor)


# ---------- Filtros ----------

def test_listar_imoveis_por_tipo_normaliza_o_valor(client, banco_mock):
    _, conexao, cursor = banco_mock
    cursor.fetchall.return_value = [IMOVEL_SALVO]

    resposta = client.get("/imoveis/tipo/APARTAMENTO")

    assert resposta.status_code == 200
    assert resposta.get_json() == [IMOVEL_SALVO]
    cursor.execute.assert_called_once_with(
        "SELECT * FROM imoveis WHERE LOWER(tipo) = %s;", ("apartamento",)
    )
    assert_recursos_fechados(conexao, cursor)


def test_listar_imoveis_por_tipo_rejeita_tipo_nao_permitido_sem_banco(client):
    with patch.object(api, "get_db_connection") as obter_conexao:
        resposta = client.get("/imoveis/tipo/loja")

    assert resposta.status_code == 400
    assert "erro" in resposta.get_json()
    obter_conexao.assert_not_called()


def test_listar_imoveis_por_cidade_retorna_registros_da_cidade(client, banco_mock):
    _, conexao, cursor = banco_mock
    cursor.fetchall.side_effect = [
        [{"cidade": "são paulo"}, {"cidade": "rio de janeiro"}],
        [IMOVEL_SALVO],
    ]

    resposta = client.get("/imoveis/cidade/S%C3%A3o%20Paulo")

    assert resposta.status_code == 200
    assert resposta.get_json() == [IMOVEL_SALVO]
    assert cursor.execute.call_count == 2
    assert cursor.execute.call_args_list[1].args[1] == ("são paulo",)
    assert_recursos_fechados(conexao, cursor)


def test_listar_imoveis_por_cidade_retorna_404_quando_cidade_nao_foi_cadastrada(
    client, banco_mock
):
    _, conexao, cursor = banco_mock
    cursor.fetchall.return_value = []

    resposta = client.get("/imoveis/cidade/Manaus")

    assert resposta.status_code == 404
    assert resposta.get_json() == {
        "erro": "Cidade não encontrada nos imóveis cadastrados"
    }
    cursor.execute.assert_called_once()
    assert_recursos_fechados(conexao, cursor)
