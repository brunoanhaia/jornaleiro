"""Testes de operacao: resolucao do config, retencao (`limpar`) e `run` com fakes."""

from __future__ import annotations

import argparse
from datetime import date, datetime
from io import BytesIO
from pathlib import Path

import pytest
from pypdf import PdfWriter

from jornaleiro import agenda, cli, notify, render
from jornaleiro.model import SP, Asset, MarketResult


class RendererFalso:
    """Renderizador de mentira: nenhum teste aqui abre navegador."""

    name = "falso"

    def get_text(self, url: str) -> str:
        return ""

    def fetch_json_in_page(self, url: str, warmup_url: str) -> str:
        return ""

    def close(self) -> None:
        pass


def pdf_vazio() -> bytes:
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    buffer = BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


def mercado_falso(key: str, label: str, conteudo: bytes):
    """Modulo de mercado de mentira, com a mesma interface de `markets/<key>.py`."""

    class MercadoFalso:
        KEY = key
        LABEL = label

        @staticmethod
        def fetch(ctx, cfg) -> MarketResult:
            return MarketResult(
                key=key,
                label=label,
                status="ok",
                assets=[
                    Asset(
                        url=f"https://exemplo.test/{key}.pdf",
                        content=conteudo,
                        kind="pdf",
                        suffix=".pdf",
                    )
                ],
                validity="15/10 - 21/10",
            )

    return MercadoFalso()


def escreve_config(tmp_path: Path, mercados: list[str]) -> Path:
    linhas = ['renderer = "jina"', 'data_dir = "data"', ""]
    for key in mercados:
        linhas += [f"[markets.{key}]", "enabled = true", ""]
    caminho = tmp_path / "config.toml"
    caminho.write_text("\n".join(linhas), encoding="utf-8")
    return caminho


def prepara_run(tmp_path: Path, monkeypatch, mercados: dict) -> Path:
    """Instala os mercados falsos, o renderer falso e grava o config.toml."""
    for key, modulo in mercados.items():
        monkeypatch.setitem(cli.REGISTRY, key, modulo)
    monkeypatch.setattr(render, "build_renderer", lambda modo=None: RendererFalso())
    return escreve_config(tmp_path, list(mercados))


def roda_run(config: Path, data_dir: Path, only: str, *extras: str, no_send: bool = True) -> int:
    comando = [
        "run",
        "--only", only,
        "--sem-comprimir",
        "--config", str(config),
        "--data-dir", str(data_dir),
        *extras,
    ]
    if no_send:
        comando.append("--no-send")
    args = cli.build_parser().parse_args(comando)
    return args.handler(args)


def test_run_grava_pdf_brutos_e_log(tmp_path, monkeypatch, capsys) -> None:
    config = prepara_run(
        tmp_path,
        monkeypatch,
        {"assai": mercado_falso("assai", "Assaí Atacadista", pdf_vazio())},
    )
    data_dir = tmp_path / "data"

    assert roda_run(config, data_dir, "assai") == 0
    capsys.readouterr()  # limpa a saida capturada

    dia = datetime.now(SP).date().isoformat()
    assert (data_dir / dia / "assai.pdf").exists()
    assert (data_dir / dia / "raw" / "assai-1.pdf").exists()

    log = (data_dir / dia / "run.log").read_text(encoding="utf-8")
    assert "==== execucao em " in log
    assert "assai: 1 pag -> " in log
    assert "Encartes Rio Claro - " in log
    assert "Falhas: nenhuma" in log


def test_run_continua_quando_um_mercado_falha(tmp_path, monkeypatch, capsys) -> None:
    config = prepara_run(
        tmp_path,
        monkeypatch,
        {
            "assai": mercado_falso("assai", "Assaí Atacadista", pdf_vazio()),
            "atacadao": mercado_falso("atacadao", "Atacadão", b"isto nao e um pdf"),
        },
    )
    data_dir = tmp_path / "data"

    assert roda_run(config, data_dir, "assai,atacadao") == 0

    dia = datetime.now(SP).date().isoformat()
    assert (data_dir / dia / "assai.pdf").exists()  # o mercado bom saiu
    assert not (data_dir / dia / "atacadao.pdf").exists()  # o ruim nao derruba o run
    saida = capsys.readouterr()
    assert "atacadao: falha: " in saida.err
    assert "Atacadão - falha: " in saida.out
    assert "Falhas: Atacadão" in saida.out


def test_localizar_config_ordem_de_preferencia(tmp_path, monkeypatch) -> None:
    explicito = tmp_path / "meu.toml"
    monkeypatch.setenv("JORNALEIRO_CONFIG", str(tmp_path / "env.toml"))

    assert cli.localizar_config(str(explicito)) == explicito
    assert cli.localizar_config(None) == tmp_path / "env.toml"

    # sem --config nem env, vale o config.toml da pasta atual
    monkeypatch.delenv("JORNALEIRO_CONFIG")
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config.toml").write_text("", encoding="utf-8")
    assert cli.localizar_config(None) == Path("config.toml")

    # sem config na pasta atual, cai na raiz do repositorio
    vazio = tmp_path / "vazio"
    vazio.mkdir()
    monkeypatch.chdir(vazio)
    raiz = Path(__file__).resolve().parents[1]
    assert cli.localizar_config(None) == raiz / "config.toml"


def test_data_dir_relativo_fica_ao_lado_do_config(tmp_path) -> None:
    config_path = tmp_path / "cfg" / "config.toml"
    config_path.parent.mkdir()
    config = {"data_dir": "dados"}

    sem_flag = cli.resolver_data_dir(argparse.Namespace(data_dir=None), config, config_path)
    com_flag = cli.resolver_data_dir(
        argparse.Namespace(data_dir=str(tmp_path / "outro")), config, config_path
    )

    assert sem_flag == config_path.parent / "dados"
    assert com_flag == tmp_path / "outro"  # --data-dir vence


def test_limpar_remove_so_coletas_antigas(tmp_path, capsys) -> None:
    config = tmp_path / "config.toml"
    config.write_text('data_dir = "data"\n', encoding="utf-8")
    data = tmp_path / "data"
    antiga = data / "2020-01-01"
    (antiga / "precos").mkdir(parents=True)
    (antiga / "x.pdf").write_bytes(b"abc")
    hoje = data / datetime.now(SP).date().isoformat()
    (hoje / "raw").mkdir(parents=True)
    (data / "raw").mkdir()  # pasta que nao e de coleta
    (data / "state.json").write_text("{}", encoding="utf-8")

    def argumentos(dry_run: bool) -> argparse.Namespace:
        return argparse.Namespace(
            dias=30, dry_run=dry_run, data_dir=str(data), config=str(config)
        )

    assert cli.cmd_limpar(argumentos(dry_run=True)) == 0
    assert antiga.exists()  # dry-run nao remove nada
    assert "seria removida" in capsys.readouterr().out

    assert cli.cmd_limpar(argumentos(dry_run=False)) == 0
    saida = capsys.readouterr().out
    assert not antiga.exists()
    assert hoje.exists()
    assert (data / "raw").exists()
    assert (data / "state.json").exists()
    assert "removidas 1 coleta(s)" in saida


def test_limpar_recusa_dias_negativos(tmp_path, capsys) -> None:
    config = tmp_path / "config.toml"
    config.write_text("", encoding="utf-8")
    args = argparse.Namespace(dias=-1, dry_run=False, data_dir=str(tmp_path), config=str(config))

    assert cli.cmd_limpar(args) == 2
    assert "--dias" in capsys.readouterr().err


class TelegramFalso:
    """Telegram de mentira: registra documentos e mensagens."""

    def __init__(self) -> None:
        self.documentos: list[str] = []
        self.mensagens: list[str] = []

    def send_message(self, text: str) -> dict:
        self.mensagens.append(text)
        return {"ok": True}

    def send_document(self, path: Path, caption: str) -> dict:
        self.documentos.append(path.name)
        return {"ok": True}


def prepara_telegram(monkeypatch, fake: TelegramFalso) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "chat")
    monkeypatch.setattr(notify, "Telegram", lambda *_, **__: fake)


def test_run_nao_reenvia_encarte_identico(tmp_path, monkeypatch) -> None:
    telegram = TelegramFalso()
    prepara_telegram(monkeypatch, telegram)
    config = prepara_run(
        tmp_path,
        monkeypatch,
        {"assai": mercado_falso("assai", "Assaí Atacadista", pdf_vazio())},
    )
    data_dir = tmp_path / "data"

    assert roda_run(config, data_dir, "assai", no_send=False) == 0
    assert telegram.documentos == ["assai.pdf"]
    assert "nao reenviado" not in telegram.mensagens[0]

    # segunda execucao no mesmo dia, mesmo conteudo: so a mensagem vai
    assert roda_run(config, data_dir, "assai", no_send=False) == 0
    assert telegram.documentos == ["assai.pdf"]
    assert "nao reenviado: igual ao de " in telegram.mensagens[1]

    # --forcar reenvia mesmo identico
    assert roda_run(config, data_dir, "assai", "--forcar", no_send=False) == 0
    assert telegram.documentos == ["assai.pdf", "assai.pdf"]


def test_validade_fim_entende_formatos_reais() -> None:
    hoje = date(2026, 10, 18)

    assert cli._validade_fim("Preços válidos para 15/10/2026", hoje) == date(2026, 10, 15)
    assert cli._validade_fim("12/10 a 19/10", hoje) == date(2026, 10, 19)
    assert cli._validade_fim("válido até 17/10/2026", hoje) == date(2026, 10, 17)
    assert cli._validade_fim("15/10 - 21/10", hoje) == date(2026, 10, 21)
    assert cli._validade_fim("29/12 a 03/01", hoje) == date(2027, 1, 3)  # virada de ano
    assert cli._validade_fim("sem data", hoje) is None
    assert cli._validade_fim(None, hoje) is None


def test_aviso_de_encarte_vencido_e_reenvio() -> None:
    resultado = MarketResult(
        key="assai", label="Assaí", status="ok", validity="01/01/2020 a 02/01/2020"
    )
    row = cli.Row(result=resultado, path=Path("x.pdf"), pular_envio=True)

    aviso = cli._aviso_do_mercado(row, {"dia": "2026-10-10"}, date(2026, 10, 18))

    assert "encarte vencido em 02/01" in aviso
    assert "nao reenviado: igual ao de 10/10" in aviso


def test_sha_dos_assets_muda_com_o_conteudo() -> None:
    a = Asset(url="u", content=b"a", kind="pdf", suffix=".pdf")
    b = Asset(url="u", content=b"b", kind="pdf", suffix=".pdf")

    mesma_coisa = cli._sha_assets([Asset(url="outra", content=b"a", kind="pdf", suffix=".pdf")])

    assert cli._sha_assets([a]) == mesma_coisa
    assert cli._sha_assets([a]) != cli._sha_assets([b])
    assert cli._sha_assets([]) == ""


def test_load_config_aplica_overrides_do_ambiente(tmp_path, monkeypatch) -> None:
    caminho = tmp_path / "config.toml"
    caminho.write_text(
        'renderer = "auto"\ndata_dir = "data"\n\n[agenda]\ntolerancia_min = 90\n\n'
        "[markets.assai]\nenabled = true\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("JORNALEIRO__AGENDA__TOLERANCIA_MIN", "15")
    monkeypatch.setenv("JORNALEIRO__AGENDA__HORARIOS", '["08:00","20:00"]')
    monkeypatch.setenv("JORNALEIRO__RENDERER", "jina")
    monkeypatch.setenv("JORNALEIRO__MARKETS__ASSAI__ENABLED", "false")
    monkeypatch.setenv("JORNALEIRO__DATA_DIR", str(tmp_path / "saida"))
    monkeypatch.setenv("JORNALEIRO__RETENCAO__DIAS", "7")
    monkeypatch.setenv("JORNALEIRO_CONFIG", str(tmp_path / "cfg"))
    monkeypatch.setenv("JORNALEIRO_NO_SANDBOX", "1")

    config = cli.load_config(caminho)

    assert config["agenda"]["tolerancia_min"] == 15  # inteiro veio do TOML
    assert config["agenda"]["horarios"] == ["08:00", "20:00"]
    assert config["renderer"] == "jina"  # string crua: TOML nao aceita `jina`
    assert config["markets"]["assai"]["enabled"] is False
    assert config["markets"]["assai"].enabled is False  # MarketCfg continua por atributo
    assert config["data_dir"] == str(tmp_path / "saida")
    assert config["retencao"]["dias"] == 7
    assert "JORNALEIRO_CONFIG" not in config and "jornaleiro_config" not in config
    assert "no_sandbox" not in config


def test_override_do_ambiente_ignora_valor_vazio_e_nome_quebrado(
    tmp_path, monkeypatch, capsys
) -> None:
    caminho = tmp_path / "config.toml"
    caminho.write_text('renderer = "auto"\n', encoding="utf-8")
    monkeypatch.setenv("JORNALEIRO__AGENDA__BATIDA_S", "")
    monkeypatch.setenv("JORNALEIRO__AGENDA____X", "1")

    config = cli.load_config(caminho)

    assert config == {
        "renderer": "auto",
        "data_dir": "data",
        "agenda": {},
        "retencao": {},
        "markets": {},
    }
    assert "[config] variavel ignorada: JORNALEIRO__AGENDA____X" in capsys.readouterr().err


def test_valor_invalido_do_ambiente_estoura_em_quem_consome(tmp_path, monkeypatch) -> None:
    caminho = tmp_path / "config.toml"
    caminho.write_text("", encoding="utf-8")
    monkeypatch.setenv("JORNALEIRO__AGENDA__BATIDA_S", "0")
    config = cli.load_config(caminho)

    with pytest.raises(ValueError, match="agenda: batida_s deve ser >= 1"):
        agenda.parametros(config["agenda"])


def test_run_usa_o_renderer_do_ambiente(tmp_path, monkeypatch) -> None:
    config = prepara_run(
        tmp_path,
        monkeypatch,
        {"assai": mercado_falso("assai", "Assaí Atacadista", pdf_vazio())},
    )
    modos: list[object] = []
    monkeypatch.setattr(
        render, "build_renderer", lambda modo=None: modos.append(modo) or RendererFalso()
    )
    monkeypatch.setenv("JORNALEIRO__RENDERER", "jina")

    assert roda_run(config, tmp_path / "data", "assai") == 0
    assert modos == ["jina"]


def test_limpar_coletas_conta_hoje_na_janela(tmp_path) -> None:
    data = tmp_path / "data"
    for nome in ("2026-10-01", "2026-11-01", "2026-11-02", "2026-11-16"):
        (data / nome).mkdir(parents=True)
        (data / nome / "x.pdf").write_bytes(b"abc")
    (data / "raw").mkdir()
    (data / "state.json").write_text("{}", encoding="utf-8")

    alvos = cli.limpar_coletas(data, 15, hoje=date(2026, 11, 16), dry_run=True)

    assert [pasta.name for pasta, _ in alvos] == ["2026-10-01", "2026-11-01"]
    assert all(pasta.exists() for pasta, _ in alvos)  # dry-run so lista
    assert not cli.limpar_coletas(tmp_path / "nao-existe", 15)

    removidas = cli.limpar_coletas(data, 15, hoje=date(2026, 11, 16))

    assert [pasta.name for pasta, _ in removidas] == ["2026-10-01", "2026-11-01"]
    assert sorted(pasta.name for pasta in data.iterdir()) == [
        "2026-11-02",
        "2026-11-16",
        "raw",
        "state.json",
    ]
    # dias=0 apaga tudo que nao e de hoje
    mantidas = cli.limpar_coletas(data, 0, hoje=date(2026, 11, 16), dry_run=True)
    assert [pasta.name for pasta, _ in mantidas] == [
        "2026-11-02"
    ]


def test_config_retencao_le_a_secao_e_valida() -> None:
    assert cli.config_retencao({}) == 15
    assert cli.config_retencao({"retencao": {"dias": 3}}) == 3
    with pytest.raises(ValueError, match="retencao: dias deve ser >= 0"):
        cli.config_retencao({"retencao": {"dias": -1}})
    with pytest.raises(ValueError, match="retencao: dias invalido"):
        cli.config_retencao({"retencao": {"dias": "abc"}})


def test_limpar_sem_dias_usa_o_config(tmp_path, capsys) -> None:
    config = tmp_path / "config.toml"
    config.write_text('data_dir = "data"\n\n[retencao]\ndias = 5\n', encoding="utf-8")
    data = tmp_path / "data"
    (data / "2020-01-01").mkdir(parents=True)
    (data / "2020-01-01" / "x.pdf").write_bytes(b"abc")
    hoje = data / datetime.now(SP).date().isoformat()
    hoje.mkdir()

    args = argparse.Namespace(dias=None, dry_run=False, data_dir=str(data), config=str(config))

    assert cli.cmd_limpar(args) == 0
    assert not (data / "2020-01-01").exists()
    assert hoje.exists()
    assert "retendo 5 dia(s)" in capsys.readouterr().out


def test_run_poda_coletas_antigas(tmp_path, monkeypatch, capsys) -> None:
    config = prepara_run(
        tmp_path,
        monkeypatch,
        {"assai": mercado_falso("assai", "Assaí Atacadista", pdf_vazio())},
    )
    config.write_text(
        config.read_text(encoding="utf-8") + "\n[retencao]\ndias = 1\n", encoding="utf-8"
    )
    data_dir = tmp_path / "data"
    velha = data_dir / "2020-01-01"
    velha.mkdir(parents=True)
    (velha / "x.pdf").write_bytes(b"abc")

    assert roda_run(config, data_dir, "assai") == 0

    dia = datetime.now(SP).date().isoformat()
    assert not velha.exists()
    assert (data_dir / dia / "assai.pdf").exists()  # o PDF do dia continua
    assert "[retencao] 1 coleta(s) removida(s)" in capsys.readouterr().out


class AgendaFalsa:
    """Agenda de mentira: guarda os argumentos e nao abre subprocesso."""

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        AgendaFalsa.ultima = self

    def executar_agora(self) -> int:
        return 1

    def rodar(self, _max_execucoes: int | None = None) -> int:
        return 0


def serve_args(config: Path, data_dir: Path, *extras: str) -> argparse.Namespace:
    comando = ["serve", "--agora", "--config", str(config), "--data-dir", str(data_dir), *extras]
    return cli.build_parser().parse_args(comando)


def prepara_serve(tmp_path, monkeypatch) -> tuple[Path, Path]:
    config = tmp_path / "config.toml"
    config.write_text('data_dir = "data"\n', encoding="utf-8")
    monkeypatch.setattr(cli.agenda, "Agenda", AgendaFalsa)
    monkeypatch.setattr(cli.agenda, "instalar_sinais", lambda: None)
    return config, tmp_path / "data"


def test_serve_sem_envio_nao_usa_o_telegram(tmp_path, monkeypatch, capsys) -> None:
    telegram = TelegramFalso()
    prepara_telegram(monkeypatch, telegram)
    config, data_dir = prepara_serve(tmp_path, monkeypatch)

    assert cli.cmd_serve(serve_args(config, data_dir, "--no-send")) == 1

    fila = AgendaFalsa.ultima
    assert fila.kwargs["estado_path"] == data_dir / "agenda.json"
    assert "--no-send" in fila.kwargs["comando"]

    fila.kwargs["avisar"]("Jornaleiro: falhou")

    assert not telegram.mensagens
    assert "Jornaleiro: falhou" in capsys.readouterr().err


def test_serve_avisa_falha_no_telegram(tmp_path, monkeypatch) -> None:
    telegram = TelegramFalso()
    prepara_telegram(monkeypatch, telegram)
    config, data_dir = prepara_serve(tmp_path, monkeypatch)

    assert cli.cmd_serve(serve_args(config, data_dir)) == 1
    AgendaFalsa.ultima.kwargs["avisar"]("Jornaleiro: falhou")

    assert telegram.mensagens == ["Jornaleiro: falhou"]


def test_serve_aviso_que_falha_nao_derruba_o_loop(tmp_path, monkeypatch, capsys) -> None:
    prepara_telegram(monkeypatch, TelegramFalso())

    class TelegramQuebrado:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        def send_message(self, _texto: str) -> dict:
            raise RuntimeError("telegram fora do ar")

    monkeypatch.setattr(notify, "Telegram", TelegramQuebrado)
    config, data_dir = prepara_serve(tmp_path, monkeypatch)

    cli.cmd_serve(serve_args(config, data_dir))
    AgendaFalsa.ultima.kwargs["avisar"]("Jornaleiro: falhou")

    assert "aviso nao enviado: RuntimeError: telegram fora do ar" in capsys.readouterr().err


def test_serve_sem_credenciais_recusa_o_envio(tmp_path, monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "load_dotenv", lambda *_, **__: None)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    config, data_dir = prepara_serve(tmp_path, monkeypatch)

    assert cli.cmd_serve(serve_args(config, data_dir)) == 2
    assert "defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID" in capsys.readouterr().err
