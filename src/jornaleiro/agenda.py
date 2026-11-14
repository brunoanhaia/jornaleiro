"""Agendador interno: dispara `jornaleiro run` nos horarios de America/Sao_Paulo.

O container nao tem cron: o proprio processo `jornaleiro serve` dorme, decide se um
horario ficou devendo (catch-up dentro de `tolerancia_min`), roda a coleta como
subprocesso e grava `data/agenda.json` (ultima execucao, proxima, falhas seguidas e
o batimento `atualizado_em` que o healthcheck consulta com `serve --verificar`).
Sem importar `notify`/`render`: o aviso de falha entra por callback.
"""

from __future__ import annotations

import signal
import subprocess
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import time as hora
from pathlib import Path

from .model import SP
from .state import State

HORARIOS_PADRAO = ("07:00", "19:00")
TOLERANCIA_PADRAO_MIN = 90
BATIDA_PADRAO_S = 30         # intervalo maximo entre gravacoes de agenda.json
ESPERA_PADRAO_S = 30         # teto de cada sono do loop
SAUDE_JANELA_PADRAO_S = 300  # healthcheck reprova se a batida estiver mais velha que isso
FALHAS_PADRAO = 3

# ligado pelo SIGTERM/SIGINT: o loop (e o run em andamento) terminam sem aviso de falha
_PARAR = False


@dataclass(frozen=True)
class Parametros:
    """Limiares da agenda, ja resolvidos (config + ambiente + CLI)."""

    slots: tuple[hora, ...]
    tolerancia_min: int
    batida_s: int
    espera_max_s: int
    saude_janela_s: int
    falhas_limite: int


def horarios(valor: str | Sequence[str] | None) -> list[hora]:
    """Horarios `HH:MM` de uma string (virgula/espaco) ou sequencia; vazio = padrao."""
    if valor is None:
        return _horarios_padrao()
    if isinstance(valor, str):
        tokens = [token for token in valor.replace(",", " ").split() if token]
    else:
        tokens = [str(token).strip() for token in valor if str(token).strip()]
    if not tokens:
        return _horarios_padrao()
    lidos: list[hora] = []
    for token in tokens:
        try:
            lidos.append(datetime.strptime(token, "%H:%M").time())
        except ValueError:
            raise ValueError(f"horario invalido: {token!r} (use HH:MM)") from None
    return sorted(set(lidos))


def _horarios_padrao() -> list[hora]:
    return [datetime.strptime(token, "%H:%M").time() for token in HORARIOS_PADRAO]


def parametros(secao: Mapping[str, object] | None = None) -> Parametros:
    """Le a secao `[agenda]` (ja com os overrides do ambiente) e valida as faixas."""
    secao = secao or {}
    tolerancia = _inteiro(secao, "tolerancia_min", TOLERANCIA_PADRAO_MIN)
    batida = _inteiro(secao, "batida_s", BATIDA_PADRAO_S)
    espera = _inteiro(secao, "espera_max_s", ESPERA_PADRAO_S)
    janela = _inteiro(secao, "saude_janela_s", SAUDE_JANELA_PADRAO_S)
    falhas = _inteiro(secao, "falhas_limite", FALHAS_PADRAO)
    for chave, minimo, valor in (
        ("tolerancia_min", 0, tolerancia),
        ("batida_s", 1, batida),
        ("espera_max_s", 1, espera),
        ("falhas_limite", 1, falhas),
    ):
        if valor < minimo:
            raise ValueError(f"agenda: {chave} deve ser >= {minimo}")
    if janela < 2 * batida:
        raise ValueError("agenda: saude_janela_s deve ser pelo menos o dobro de batida_s")
    return Parametros(
        slots=tuple(horarios(secao.get("horarios"))),
        tolerancia_min=tolerancia,
        batida_s=batida,
        espera_max_s=espera,
        saude_janela_s=janela,
        falhas_limite=falhas,
    )


def _inteiro(secao: Mapping[str, object], chave: str, padrao: int) -> int:
    valor = secao.get(chave, padrao)
    try:
        return int(str(valor).strip())
    except (TypeError, ValueError):
        raise ValueError(f"agenda: {chave} invalido: {valor!r} (esperado inteiro)") from None


def proxima_execucao(agora: datetime, slots: Sequence[hora]) -> datetime:
    """Primeiro horario estritamente depois de `agora` (hoje ou amanha)."""
    candidatos: list[datetime] = []
    for dias in (0, 1):
        dia = agora.date() + timedelta(days=dias)
        for slot in slots:
            quando = datetime.combine(dia, slot, tzinfo=agora.tzinfo)
            if quando > agora:
                candidatos.append(quando)
    if not candidatos:
        raise ValueError("agenda: sem horarios configurados")
    return min(candidatos)


def devida(
    agora: datetime, slots: Sequence[hora], tolerancia_min: int, estado: dict
) -> datetime | None:
    """Ultimo horario vencido dentro da tolerancia e ainda nao executado (catch-up)."""
    vencido = None
    for slot in slots:
        quando = datetime.combine(agora.date(), slot, tzinfo=agora.tzinfo)
        if quando <= agora and (vencido is None or quando > vencido):
            vencido = quando
    if vencido is None:
        return None
    if agora - vencido > timedelta(minutes=tolerancia_min):
        return None
    if _rodou_desde(estado, vencido):
        return None
    return vencido


def _rodou_desde(estado: dict, marca: datetime) -> bool:
    """Se `ultima.inicio` do estado e legivel e cai em/after de `marca`."""
    ultima = estado.get("ultima")
    if not isinstance(ultima, dict):
        return False
    inicio = ultima.get("inicio")
    if not isinstance(inicio, str):
        return False
    try:
        quando = datetime.fromisoformat(inicio)
        return quando >= marca  # fuso incomparavel (naive x aware) cai no except
    except (TypeError, ValueError):
        return False  # estado corrompido conta como "nunca rodou"


def verificar(
    estado: dict, agora: datetime, *, saude_janela_s: int, falhas_limite: int
) -> str | None:
    """Motivo de o agendador estar doente, ou None quando o batimento esta em dia."""
    atualizado = estado.get("atualizado_em")
    if not isinstance(atualizado, str) or not atualizado:
        return "agenda.json sem atualizado_em"
    try:
        quando = datetime.fromisoformat(atualizado)
        parado = (agora - quando).total_seconds()
    except (TypeError, ValueError):
        return f"agenda.json com atualizado_em ilegivel: {atualizado!r}"
    if parado > saude_janela_s:
        return f"agenda parada ha {int(parado)}s"
    falhas = estado.get("falhas_seguidas")
    if isinstance(falhas, int) and falhas >= falhas_limite:
        return f"{falhas} execucoes seguidas com falha"
    return None


def comando(config: Path, data_dir: Path | None, no_send: bool) -> list[str]:
    """Comando do run disparado pela agenda (mesmo Python, mesmo config)."""
    cmd = [sys.executable, "-m", "jornaleiro", "run", "--config", str(config)]
    if data_dir:
        cmd += ["--data-dir", str(data_dir)]
    if no_send:
        cmd.append("--no-send")
    return cmd


class Agenda:
    """Loop do agendador: dorme, verifica a agenda e dispara o run como filho."""

    def __init__(
        self,
        *,
        params: Parametros,
        estado_path: Path,
        comando: list[str],
        log_dir: Path,
        avisar: Callable[[str], None],
        relogio: Callable[[], datetime] = lambda: datetime.now(SP),
        dormir: Callable[[float], None] = time.sleep,
    ) -> None:
        self.params = params
        self.comando = list(comando)
        self.log_dir = log_dir
        self.avisar = avisar
        self.relogio = relogio
        self.dormir = dormir
        self._estado = State.load(estado_path)
        self.ultimo_codigo: int = 0

    def executar_agora(self) -> int:
        """Roda a coleta uma vez e anota o resultado (e avisa quando falha)."""
        inicio = self.relogio()
        code, fim = self._executar()
        segundos = (fim - inicio).total_seconds()
        self._estado.data["ultima"] = {
            "inicio": inicio.isoformat(),
            "fim": fim.isoformat(),
            "codigo": code,
        }
        falhas = self._estado.get("falhas_seguidas")
        falhas = falhas if isinstance(falhas, int) else 0
        if not _PARAR:
            falhas = falhas + 1 if code != 0 else 0
        self._estado.data["falhas_seguidas"] = falhas
        agora = self.relogio()
        proxima = proxima_execucao(agora, self.params.slots)
        self._estado.data["proxima"] = proxima.isoformat()
        self._estado.data["atualizado_em"] = agora.isoformat()
        self._estado.save()
        self.ultimo_codigo = code
        if code != 0 and not _PARAR:
            self.avisar(
                f"Jornaleiro: execucao das {inicio:%d/%m %H:%M} falhou (codigo {code}) "
                f"em {segundos:.0f}s.\n"
                f"Log: {self.log_dir / f'{inicio:%Y-%m-%d}' / 'run.log'}\n"
                f"Proxima: {proxima:%d/%m %H:%M}"
            )
        return code

    def _executar(self) -> tuple[int, datetime]:
        """Roda o subprocesso do run, batendo o coracao enquanto ele nao termina."""
        proc = subprocess.Popen(self.comando)
        ultima_batida = self.relogio()
        try:
            while proc.poll() is None:
                if _PARAR:
                    proc.terminate()
                    try:
                        proc.wait(timeout=30)
                    except subprocess.TimeoutExpired:
                        proc.kill()
                        proc.wait()
                    break
                self.dormir(1)
                if (self.relogio() - ultima_batida).total_seconds() >= self.params.batida_s:
                    self._bater()
                    ultima_batida = self.relogio()
        finally:
            if proc.returncode is None:
                proc.terminate()
                proc.wait()
        return int(proc.returncode), self.relogio()

    def _bater(self) -> None:
        """Atualiza so o batimento (o healthcheck nao reprova durante um run longo)."""
        self._estado.data["atualizado_em"] = self.relogio().isoformat()
        self._estado.save()

    def passo(self) -> bool:
        """Um ciclo do loop: executa se havia horario devendo; senao so bate o ponto."""
        agora = self.relogio()
        slot = devida(agora, self.params.slots, self.params.tolerancia_min, self._estado.data)
        if slot is not None:
            self.executar_agora()
            return True
        self._estado.data["atualizado_em"] = agora.isoformat()
        self._estado.data["proxima"] = proxima_execucao(agora, self.params.slots).isoformat()
        self._estado.save()
        return False

    def rodar(self, max_execucoes: int | None = None) -> int:
        """Loop principal; `max_execucoes` para os testes (None = para so no sinal)."""
        executadas = 0
        self._anunciar()
        while not _PARAR:
            if self.passo():
                executadas += 1
                if max_execucoes is not None and executadas >= max_execucoes:
                    return 0
                self._anunciar()
            falta = (
                proxima_execucao(self.relogio(), self.params.slots) - self.relogio()
            ).total_seconds()
            self.dormir(min(float(self.params.espera_max_s), max(1.0, falta)))
        return 0

    def _anunciar(self) -> None:
        proxima = proxima_execucao(self.relogio(), self.params.slots)
        print(f"[agenda] proxima execucao: {proxima:%d/%m %H:%M}", flush=True)


def instalar_sinais() -> None:
    """SIGTERM/SIGINT apenas ligam `_PARAR`: o loop encerra sem aviso de falha."""

    def _parar(_signum: int, _frame: object) -> None:
        global _PARAR
        _PARAR = True
        print("[agenda] encerrando...", flush=True)

    signal.signal(signal.SIGTERM, _parar)
    signal.signal(signal.SIGINT, _parar)
