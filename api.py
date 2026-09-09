"""API REST para consulta e manutenção de imóveis."""

from flask import Flask, jsonify, request, url_for
import mysql.connector

from connect_db import get_db_connection


app = Flask(__name__)

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

TIPOS_PERMITIDOS = {
    "casa",
    "apartamento",
    "terreno",
    "casa em condominio",
}


def _fechar_recursos(cursor, conexao):
    """Fecha cursor e conexão quando eles tiverem sido abertos."""
    if cursor:
        cursor.close()
    if conexao and conexao.is_connected():
        conexao.close()


def _link(endpoint, method="GET", **valores):
    """Cria um controle de hipermídia para uma rota da própria API.

    ``url_for`` mantém os links alinhados às rotas Flask e usa o host da
    requisição atual. Assim, os mesmos links funcionam localmente, na EC2 e em
    qualquer ambiente que publique a aplicação.
    """
    return {
        "href": url_for(endpoint, _external=True, **valores),
        "method": method,
    }


def _links_da_colecao():
    """Retorna ações disponíveis a partir da coleção de imóveis."""
    return {
        "collection": _link("listar_imoveis"),
        "create": _link("adicionar_imovel", method="POST"),
    }


def _serializar_imovel(imovel):
    """Acrescenta controles HATEOAS à representação de um imóvel."""
    representacao = dict(imovel)
    imovel_id = representacao["id"]

    links = {
        "self": _link("obter_imovel", imovel_id=imovel_id),
        "collection": _link("listar_imoveis"),
        "update": _link("atualizar_imovel", method="PUT", imovel_id=imovel_id),
        "delete": _link("deletar_imovel", method="DELETE", imovel_id=imovel_id),
    }

    tipo = representacao.get("tipo")
    if tipo:
        links["by_type"] = _link(
            "listar_imoveis_por_tipo", tipo=str(tipo).strip().lower()
        )

    cidade = representacao.get("cidade")
    if cidade:
        links["by_city"] = _link(
            "listar_imoveis_por_cidade", cidade=str(cidade).strip().lower()
        )

    representacao["_links"] = links
    return representacao


def _serializar_colecao(imoveis, endpoint, **valores):
    """Representa uma coleção com itens navegáveis e links de transição."""
    return {
        "items": [_serializar_imovel(imovel) for imovel in imoveis],
        "_links": {
            "self": _link(endpoint, **valores),
            **_links_da_colecao(),
        },
    }


def _resposta_erro(mensagem, status):
    """Devolve erros JSON com uma transição para retomar a navegação."""
    return jsonify({"erro": mensagem, "_links": _links_da_colecao()}), status


def _obter_dados_do_imovel():
    """Lê e valida o corpo JSON usado nas operações de escrita.

    A validação ocorre antes de abrir uma conexão com o banco. Além de evitar
    trabalho desnecessário, isso permite devolver uma resposta JSON consistente
    para corpo ausente ou JSON malformado.
    """
    dados = request.get_json(silent=True)

    if not isinstance(dados, dict):
        return (
            None,
            jsonify(
                {
                    "erro": "Corpo da requisição deve ser um JSON válido",
                    "_links": _links_da_colecao(),
                }
            ),
            400,
        )

    campos_ausentes = [campo for campo in CAMPOS_OBRIGATORIOS if campo not in dados]
    if campos_ausentes:
        return (
            None,
            jsonify(
                {
                    "erro": (
                        "Campos obrigatórios: logradouro, tipo_logradouro, bairro, "
                        "cidade, cep, tipo, valor e data_aquisicao"
                    ),
                    "_links": _links_da_colecao(),
                }
            ),
            400,
        )

    return dados, None, None


@app.route("/imoveis", methods=["GET"])
def listar_imoveis():
    """Retorna todos os imóveis cadastrados no banco MySQL."""
    conexao = None
    cursor = None
    try:
        conexao = get_db_connection()
        cursor = conexao.cursor(dictionary=True)
        cursor.execute("SELECT * FROM imoveis;")
        return jsonify(_serializar_colecao(cursor.fetchall(), "listar_imoveis")), 200
    except mysql.connector.Error as err:
        return _resposta_erro(f"Falha ao consultar o banco de dados: {err}", 500)
    finally:
        _fechar_recursos(cursor, conexao)


@app.route("/imoveis/<int:imovel_id>", methods=["GET"])
def obter_imovel(imovel_id):
    """Busca um imóvel específico pelo ID."""
    conexao = None
    cursor = None
    try:
        conexao = get_db_connection()
        cursor = conexao.cursor(dictionary=True)
        cursor.execute("SELECT * FROM imoveis WHERE id = %s;", (imovel_id,))
        imovel = cursor.fetchone()

        if imovel:
            return jsonify(_serializar_imovel(imovel)), 200
        return _resposta_erro("Imóvel não encontrado", 404)
    except mysql.connector.Error as err:
        return _resposta_erro(f"Falha ao consultar o banco de dados: {err}", 500)
    finally:
        _fechar_recursos(cursor, conexao)


@app.route("/imoveis", methods=["POST"])
def adicionar_imovel():
    """Cadastra um novo imóvel no banco MySQL."""
    novo_imovel, erro_json, status_erro = _obter_dados_do_imovel()
    if erro_json:
        return erro_json, status_erro

    conexao = None
    cursor = None
    try:
        conexao = get_db_connection()
        cursor = conexao.cursor(dictionary=True)
        cursor.execute(
            """
            INSERT INTO imoveis (
                logradouro, tipo_logradouro, bairro, cidade,
                cep, tipo, valor, data_aquisicao
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """,
            tuple(novo_imovel[campo] for campo in CAMPOS_OBRIGATORIOS),
        )
        conexao.commit()
        representacao = _serializar_imovel({**novo_imovel, "id": cursor.lastrowid})
        return (
            jsonify(representacao),
            201,
            {"Location": representacao["_links"]["self"]["href"]},
        )
    except mysql.connector.Error as err:
        return _resposta_erro(f"Falha ao consultar o banco de dados: {err}", 500)
    finally:
        _fechar_recursos(cursor, conexao)


@app.route("/imoveis/<int:imovel_id>", methods=["PUT"])
def atualizar_imovel(imovel_id):
    """Atualiza um imóvel específico pelo ID."""
    imovel_atualizado, erro_json, status_erro = _obter_dados_do_imovel()
    if erro_json:
        return erro_json, status_erro

    conexao = None
    cursor = None
    try:
        conexao = get_db_connection()
        cursor = conexao.cursor(dictionary=True)
        cursor.execute(
            """
            UPDATE imoveis SET
                logradouro = %s,
                tipo_logradouro = %s,
                bairro = %s,
                cidade = %s,
                cep = %s,
                tipo = %s,
                valor = %s,
                data_aquisicao = %s
            WHERE id = %s
            """,
            (*tuple(imovel_atualizado[campo] for campo in CAMPOS_OBRIGATORIOS), imovel_id),
        )
        conexao.commit()

        if cursor.rowcount == 1:
            representacao = _serializar_imovel({**imovel_atualizado, "id": imovel_id})
            representacao["mensagem"] = "Imóvel atualizado com sucesso"
            return jsonify(representacao), 200
        return _resposta_erro("Imóvel não encontrado", 404)
    except mysql.connector.Error as err:
        return _resposta_erro(f"Falha ao consultar o banco de dados: {err}", 500)
    finally:
        _fechar_recursos(cursor, conexao)


@app.route("/imoveis/<int:imovel_id>", methods=["DELETE"])
def deletar_imovel(imovel_id):
    """Exclui um imóvel específico pelo ID."""
    conexao = None
    cursor = None
    try:
        conexao = get_db_connection()
        cursor = conexao.cursor(dictionary=True)
        cursor.execute("DELETE FROM imoveis WHERE id = %s;", (imovel_id,))
        conexao.commit()

        if cursor.rowcount == 1:
            return (
                jsonify(
                    {
                        "mensagem": "Imóvel excluído com sucesso",
                        "_links": _links_da_colecao(),
                    }
                ),
                200,
            )
        return _resposta_erro("Imóvel não encontrado", 404)
    except mysql.connector.Error as err:
        return _resposta_erro(f"Falha ao consultar o banco de dados: {err}", 500)
    finally:
        _fechar_recursos(cursor, conexao)


@app.route("/imoveis/tipo/<string:tipo>", methods=["GET"])
def listar_imoveis_por_tipo(tipo):
    """Retorna todos os imóveis de um tipo específico."""
    tipo_normalizado = tipo.strip().lower()
    if tipo_normalizado not in TIPOS_PERMITIDOS:
        return _resposta_erro(
            "Tipo inválido. Use: casa, apartamento, terreno ou casa em condominio",
            400,
        )

    conexao = None
    cursor = None
    try:
        conexao = get_db_connection()
        cursor = conexao.cursor(dictionary=True)
        cursor.execute(
            "SELECT * FROM imoveis WHERE LOWER(tipo) = %s;", (tipo_normalizado,)
        )
        return (
            jsonify(
                _serializar_colecao(
                    cursor.fetchall(),
                    "listar_imoveis_por_tipo",
                    tipo=tipo_normalizado,
                )
            ),
            200,
        )
    except mysql.connector.Error as err:
        return _resposta_erro(f"Falha ao consultar o banco de dados: {err}", 500)
    finally:
        _fechar_recursos(cursor, conexao)


@app.route("/imoveis/cidade/<string:cidade>", methods=["GET"])
def listar_imoveis_por_cidade(cidade):
    """Retorna todos os imóveis de uma cidade específica."""
    conexao = None
    cursor = None
    try:
        conexao = get_db_connection()
        cursor = conexao.cursor(dictionary=True)
        cidade_normalizada = cidade.strip().lower()

        cursor.execute(
            """
            SELECT DISTINCT LOWER(TRIM(cidade)) AS cidade
            FROM imoveis
            WHERE cidade IS NOT NULL
              AND TRIM(cidade) <> '';
            """
        )
        cidades_permitidas = {item["cidade"] for item in cursor.fetchall()}

        if cidade_normalizada not in cidades_permitidas:
            return _resposta_erro("Cidade não encontrada nos imóveis cadastrados", 404)

        cursor.execute(
            """
            SELECT *
            FROM imoveis
            WHERE LOWER(TRIM(cidade)) = %s;
            """,
            (cidade_normalizada,),
        )
        return (
            jsonify(
                _serializar_colecao(
                    cursor.fetchall(),
                    "listar_imoveis_por_cidade",
                    cidade=cidade_normalizada,
                )
            ),
            200,
        )
    except mysql.connector.Error as err:
        return _resposta_erro(f"Falha ao consultar o banco de dados: {err}", 500)
    finally:
        _fechar_recursos(cursor, conexao)


if __name__ == "__main__":
    app.run(debug=True)
