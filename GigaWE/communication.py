# -*- coding: utf-8 -*-
from __future__ import print_function
import time
import re
import serial
import serial.tools.list_ports

from config import (
    BAUD_RATE      as SER_BAUD,
    SER_TIMEOUT,
    WRITE_TIMEOUT,
    PRE_DELAY_DEFAULT,
    PRE_DELAY_SENSOR,
    INTER_CMD_DELAY,
    POST_DRAIN_TIME,
    RETRIES,
)

EOL = b"\r\n"


# ==================== Utilidades de porta ====================
def list_ports():
    return [p.device for p in serial.tools.list_ports.comports()]

def _open(port):
    return serial.Serial(
        port=port,
        baudrate=SER_BAUD,
        timeout=SER_TIMEOUT,
        write_timeout=WRITE_TIMEOUT
    )

def _friendly_err(e):
    msg = str(e) or e.__class__.__name__
    if "PermissionError" in msg or "denied" in msg:
        return "Sem permissão para abrir a porta (adicione seu usuário ao grupo 'dialout' e relogue)."
    if "No such file" in msg or "FileNotFoundError" in msg:
        return "Porta não encontrada/desconectada."
    if "busy" in msg.lower():
        return "Porta ocupada por outro programa."
    return msg


# ==================== Helpers de parsing ====================
def _strip_prefix(cmd_qmark, value_str):
    """Remove prefixos '+CMD:', 'CMD:' e 'CMD=' (case-insensitive)."""
    try:
        name = cmd_qmark.upper().replace("AT+", "").replace("?", "").strip()
        s = (value_str or "").strip()
        up = s.upper()
        for pref in (name + ":", "+" + name + ":", name + "="):
            if up.startswith(pref):
                return s[len(pref):].strip()
        return s
    except Exception:
        return (value_str or "").strip()

def _normalize_value(cmd_qmark, val):
    """Mapeia CONN/DHCP para textos amigáveis (sem alterar números)."""
    name = cmd_qmark.upper().replace("AT+", "").replace("?", "").strip()
    v = (val or "").strip()
    if name == "CONN":
        if v in ("0", "WIFI", "WI-FI", "WI_FI"):
            return "Wi-Fi"
        if v in ("1", "ETH", "ETHERNET"):
            return "Ethernet"
    if name == "DHCP":
        if v in ("1", "ON", "On", "on"):
            return "ON"
        if v in ("0", "OFF", "Off", "off"):
            return "OFF"
    return v

def _is_noise_line(txt):
    """Elimina eco/logs assíncronos que não são o valor."""
    up = (txt or "").strip().upper()
    if not up:
        return True
    if up in ("OK", "ERROR"):
        return True
    if up.startswith("AT+"):
        return True
    # logs do firmware durante busca de sensores
    if "PROCURANDO" in up and "SENSOR" in up and "PORTA" in up:
        return True
    if up.startswith("TENTATIVAS"):
        return True
    if up.startswith("ID [HEXA]") or up.startswith("ID ="):
        return True
    if up.startswith("TEMPERATURA"):
        return True
    return False

def _drain(serial_obj, dur=POST_DRAIN_TIME):
    """Drena bytes residuais por 'dur' segundos (evita 'vazamento' p/ próximo comando)."""
    end = time.time() + (dur or 0)
    while time.time() < end:
        serial_obj.read(256)  # descarta
        time.sleep(0.01)

def _query_lines(port, cmd, pre_delay=0.0, extra_timeout=0.0):
    """
    Envia 'AT+CMD?' e lê **linha a linha** até 'OK'/'ERROR' ou timeout.
    pre_delay: tempo de espera ANTES de começar a ler.
    extra_timeout: tempo adicional ao SER_TIMEOUT (p/ comandos demorados).
    Retorna lista de strings (sem CR/LF).
    """
    payload = (cmd + "\r\n").encode("utf-8")
    lines = []
    with _open(port) as s:
        s.reset_input_buffer()
        s.reset_output_buffer()
        s.write(payload)
        s.flush()
        if pre_delay and pre_delay > 0:
            time.sleep(pre_delay)
        end = time.time() + SER_TIMEOUT + (extra_timeout or 0.0)
        while time.time() < end:
            ln = s.readline()
            if not ln:
                time.sleep(0.03)
                continue
            txt = ln.decode("utf-8", "ignore").replace("\r", "").strip()
            if txt:
                lines.append(txt)
            up = txt.upper()
            if up in ("OK", "ERROR"):
                break
        # drena qualquer resíduo após OK/ERROR
        _drain(s)
    return lines

def _parse_from_lines(cmd_qmark, lines):
    """Remove eco/logs e pega a última linha relevante antes do OK."""
    cands = []
    for ln in lines:
        if _is_noise_line(ln):
            continue
        cands.append(_strip_prefix(cmd_qmark, ln))
    if not cands:
        return ""
    return cands[-1].strip()

def _parse_sensors_from_text(text):
    """Extrai s0 e s2 do texto (aceita vírgula ou ponto como decimal)."""
    m0 = re.search(r"s0\s*=\s*([0-9]+(?:[.,][0-9]+)?)", text, re.IGNORECASE)
    m2 = re.search(r"s2\s*=\s*([0-9]+(?:[.,][0-9]+)?)", text, re.IGNORECASE)
    s0 = m0.group(1) if m0 else ""
    s2 = m2.group(1) if m2 else ""
    return (s0, s2)

def _peek_sensor_from_buffer(port, dur=0.9):
    """
    Plano B: NÃO envia novo comando; apenas lê o que ainda possa chegar
    no buffer por 'dur' segundos e tenta extrair s0/s2.
    """
    try:
        with _open(port) as s:
            end = time.time() + (dur or 0)
            buf = b""
            while time.time() < end:
                chunk = s.read(256)
                if chunk:
                    buf += chunk
                else:
                    time.sleep(0.03)
        text = buf.decode("utf-8", "ignore")
        return _parse_sensors_from_text(text)
    except Exception:
        return ("", "")


# ==================== API pública ====================
def write_at_command(port, cmd, value):
    """
    Envia 'AT+CMD' ou 'AT+CMD=value' e espera 'OK', com delay antes da leitura
    e dreno após o término.
    """
    line = cmd if (value is None or value == "") else "{}={}".format(cmd, value)
    payload = (line + "\r\n").encode("utf-8")

    for _ in range(RETRIES + 1):
        try:
            with _open(port) as s:
                s.reset_input_buffer()
                s.reset_output_buffer()
                s.write(payload)
                s.flush()
                time.sleep(PRE_DELAY_DEFAULT)
                end = time.time() + SER_TIMEOUT
                buf = b""
                ok = False
                while time.time() < end:
                    chunk = s.read(128)
                    if chunk:
                        buf += chunk
                        up = buf.upper()
                        if b"\nOK" in up or up.strip().endswith(b"OK"):
                            ok = True
                            break
                        if b"\nERROR" in up or up.strip().endswith(b"ERROR"):
                            ok = False
                            break
                    else:
                        time.sleep(0.02)
                _drain(s)  # drena sobra
                return ok
        except Exception:
            time.sleep(0.12)
    return False

def read_value(port, cmd_qmark, pre_delay=None):
    """Lê valor de um comando '?': envia, espera, lê até OK (com dreno)."""
    if pre_delay is None:
        pre_delay = PRE_DELAY_DEFAULT
    try:
        lines = _query_lines(port, cmd_qmark, pre_delay=pre_delay)
        val = _parse_from_lines(cmd_qmark, lines)
        val = _normalize_value(cmd_qmark, val)
        if val:
            return val
    except Exception:
        pass
    # retry
    try:
        lines = _query_lines(port, cmd_qmark, pre_delay=pre_delay)
        val = _parse_from_lines(cmd_qmark, lines)
        return _normalize_value(cmd_qmark, val)
    except Exception:
        return ""

def read_sensors(port):
    """
    Lê 'AT+SENSOR?' nos dois formatos:
      1) verboso (com logs e/ou 'OK' no fim)
      2) curto: '+SENSOR:s0=22.31,s2=22.43,' (pode não ter 'OK')
    Retorna (s0, s2) como strings, preservando vírgula/ponto.
    Estratégia:
      - envia o comando e vai lendo CHUNKS; assim que achar s0/s2 no buffer, retorna
      - se não achar, tenta extrair do que já chegou
      - por fim, reenvia uma única vez com espera maior
    """
    def _scan_until(end_extra=1.0, pre_delay=PRE_DELAY_SENSOR):
        try:
            with _open(port) as s:
                s.reset_input_buffer()
                s.reset_output_buffer()
                s.write(b"AT+SENSOR?\r\n")
                s.flush()
                if pre_delay and pre_delay > 0:
                    time.sleep(pre_delay)

                # janela de leitura (não depende de 'OK')
                end = time.time() + SER_TIMEOUT + (end_extra or 0.0)
                buf = b""
                while time.time() < end:
                    chunk = s.read(256)
                    if chunk:
                        buf += chunk
                        text = buf.decode("utf-8", "ignore")
                        s0, s2 = _parse_sensors_from_text(text)
                        if s0 or s2:
                            _drain(s)
                            return (s0, s2)
                    else:
                        time.sleep(0.03)

                # plano B: tenta do que já veio
                text = buf.decode("utf-8", "ignore")
                s0, s2 = _parse_sensors_from_text(text)
                if s0 or s2:
                    _drain(s)
                    return (s0, s2)
        except Exception:
            pass
        return ("", "")

    # Plano A: leitura normal
    s0, s2 = _scan_until(end_extra=1.0, pre_delay=PRE_DELAY_SENSOR)
    if s0 or s2:
        return (s0, s2)

    # Plano C: reenviar uma vez com espera maior
    return _scan_until(end_extra=1.5, pre_delay=PRE_DELAY_SENSOR + 0.5)

def test_connection(port):
    """Ping simples com 'AT' (sem efeitos colaterais)."""
    try:
        with _open(port) as s:
            s.reset_input_buffer()
            s.reset_output_buffer()
            s.write(b"AT" + EOL)
            s.flush()
            time.sleep(0.05)
            data = s.read(64)
            return bool(data)
    except Exception:
        return False

def test_device(port):
    """
    Lê várias chaves com DELAY entre elas.
    Retorna dict LIMPO com: MODEL, VERSION, ID, CONN, DHCP, SSID, PASSWD, IP,
                            GATEWAY, NETMASK, DNS, INTERVAL, SENSOR1, SENSOR2
    """
    out = {}
    def put(k, v):
        if v is not None:
            out[k] = v

    def q(name, cmd, pre=None):
        try:
            put(name, read_value(port, cmd, pre_delay=pre))
        except Exception:
            pass
        time.sleep(INTER_CMD_DELAY)  # delay ENTRE comandos

    q("MODEL",    "AT+MODEL?")
    q("VERSION",  "AT+VERSION?")
    q("ID",       "AT+ID?")
    q("CONN",     "AT+CONN?")
    q("DHCP",     "AT+DHCP?")
    q("SSID",     "AT+SSID?")
    q("PASSWD",   "AT+PASSWD?")
    q("IP",       "AT+IP?")
    q("GATEWAY",  "AT+GATEWAY?")
    q("NETMASK",  "AT+NETMASK?")
    q("DNS",      "AT+DNS?")
    q("INTERVAL", "AT+INTERVAL?")

    s0, s2 = read_sensors(port)  # já inclui delays e timeout extra
    put("SENSOR1", s0)
    put("SENSOR2", s2)

    return out

def read_ifconfig(port):
    """
    Lê AT+IFCONFIG? e retorna dicionário com as chaves:
    IFACE, SSID, MAC, DHCP, IP, GATEWAY, NETMASK, NAMESERVERS, CONNECTED
    """
    try:
        with serial.Serial(port, 115200, timeout=1) as ser:
            ser.write(b"AT+IFCONFIG?\r\n")
            time.sleep(1.0)
            raw = ser.read_all().decode(errors="ignore")
    except Exception as e:
        print("Erro IFCONFIG:", e)
        return {}

    lines = [l.strip() for l in raw.splitlines() if l.strip()]

    d = {
        "IFACE": "",
        "SSID": "",
        "MAC": "",
        "DHCP": "",
        "IP": "",
        "GATEWAY": "",
        "NETMASK": "",
        "NAMESERVERS": "",
        "CONNECTED": ""
    }

    for l in lines:
        if "Link encap" in l:
            # Link encap:wlan SSID:smetro HWaddr:....
            parts = l.split()
            for p in parts:
                if p.startswith("Link"):
                    d["IFACE"] = p.split(":")[1]
                elif p.startswith("SSID:"):
                    d["SSID"] = p.split(":",1)[1]
                elif p.startswith("HWaddr:"):
                    d["MAC"] = p.split(":",1)[1]
                elif p.startswith("DHCP:"):
                    d["DHCP"] = p.split(":",1)[1]

        elif "inet addr" in l:
            # inet addr:192.168.1.175  GW:192.168.1.1  Mask:255.255.255.0
            parts = l.split()
            for p in parts:
                if p.startswith("addr:"):
                    d["IP"] = p.split(":",1)[1]
                elif p.startswith("GW:"):
                    d["GATEWAY"] = p.split(":",1)[1]
                elif p.startswith("Mask:"):
                    d["NETMASK"] = p.split(":",1)[1]

        elif "Nameserver" in l:
            d["NAMESERVERS"] = l.split(":",1)[1]

        elif "Connection" in l:
            d["CONNECTED"] = l.split(":",1)[1]

    return d

def debug_read_ifconfig(port):
    """
    Envia AT+IFCONFIG? e retorna a resposta bruta (string),
    sem fazer parsing, apenas para debug.
    """
    try:
        with serial.Serial(port, 115200, timeout=1) as ser:
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            ser.write(b"AT+IFCONFIG?\r\n")
            print("[DEBUG] Enviado: AT+IFCONFIG?")
            time.sleep(1.5)  # pode ajustar se precisar

            raw = ser.read_all().decode(errors="ignore")
            print("[DEBUG] Resposta IFCONFIG (bruta):")
            print(raw)
            return raw
    except Exception as e:
        print("[DEBUG] Erro em debug_read_ifconfig:", e)
        return ""

def parse_ifconfig(raw):
    """
    Recebe o texto bruto vindo do AT+IFCONFIG? e retorna dicionário:
      IFACE, SSID, MAC, DHCP, IP, GATEWAY, NETMASK,
      NAMESERVERS, CONNECTED
    """
    d = {
        "IFACE": "",
        "SSID": "",
        "MAC": "",
        "DHCP": "",
        "IP": "",
        "GATEWAY": "",
        "NETMASK": "",
        "NAMESERVERS": "",
        "CONNECTED": ""
    }

    lines = [l.strip() for l in raw.splitlines() if l.strip()]

    for l in lines:

        # 1) Linha principal
        if "Link encap" in l:
            # Example:
            # Link encap:wlan SSID:SMETRO-2.4G HWaddr:0c:88:95:d1:0e:20 DHCP:On
            parts = l.split()
            for p in parts:
                if "encap:" in p:
                    d["IFACE"] = p.split("encap:")[1]
                elif p.startswith("SSID:"):
                    d["SSID"] = p.split(":",1)[1]
                elif p.startswith("HWaddr:"):
                    d["MAC"] = p.split(":",1)[1]
                elif p.startswith("DHCP:"):
                    d["DHCP"] = p.split(":",1)[1]

        # 2) Linha do IP / Gateway / Mask
        if "inet addr" in l:
            parts = l.split()
            for p in parts:
                if "addr:" in p:
                    d["IP"] = p.split("addr:")[1]
                elif p.startswith("GW:"):
                    d["GATEWAY"] = p.split(":",1)[1]
                elif p.startswith("Mask:"):
                    d["NETMASK"] = p.split("Mask:")[1]

        # 3) Nameservers
        if "Nameserver:" in l:
            d["NAMESERVERS"] = l.split(":",1)[1]

        # 4) Connection status
        if "Connection:" in l:
            d["CONNECTED"] = l.split(":",1)[1]

    return d

def detect_sensor(port, pre_delay=None, extra_timeout=3.0):
    """
    Envia AT+DETECT? para a WE e interpreta a resposta.

    Exemplo de resposta:
        +DETECT: DS18B20 id=11539503596508929 s0=26.25
        OK

    Retorna dict:
        {
            "type": "DS18B20",
            "id": "11539503596508929",
            "value": 26.25,
            "raw": "<todas as linhas recebidas>"
        }

    Levanta exceções em caso de erro de comunicação ou se não conseguir interpretar.
    """
    if pre_delay is None:
        # Usa o mesmo delay de sensor, porque o DETECT pode demorar
        pre_delay = PRE_DELAY_SENSOR  # hoje = 1.0 s

    try:
        # Reaproveita a infra de leitura linha-a-linha
        lines = _query_lines(
            port,
            "AT+DETECT?",
            pre_delay=pre_delay,
            extra_timeout=extra_timeout  # adiciona alguns segundos além do SER_TIMEOUT
        )
    except Exception as e:
        raise RuntimeError("Erro na comunicação serial durante AT+DETECT?: {}".format(e))

    raw = "\n".join(lines)

    tipo = None
    sensor_id = None
    valor = None

    # Procura a linha que começa com +DETECT
    for linha in lines:
        l = linha.strip()
        if not l.startswith("+DETECT"):
            continue

        # Remove o prefixo "+DETECT:" ou "+DETECT"
        if ":" in l:
            _, resto = l.split(":", 1)
        else:
            resto = l[len("+DETECT"):]

        # Ex.: " DS18B20 id=11539503596508929 s0=26.25"
        partes = resto.strip().split()
        # partes[0] -> tipo
        if len(partes) > 0:
            tipo = partes[0]

        # Demais partes: id=..., s0=...
        for p in partes[1:]:
            if p.startswith("id="):
                sensor_id = p.split("=", 1)[1]
            elif p.startswith("s0="):
                try:
                    valor_str = p.split("=", 1)[1].replace(",", ".")
                    valor = float(valor_str)
                except ValueError:
                    valor = None

        break  # já tratou a linha de interesse

    if not tipo and not sensor_id and valor is None:
        # Não conseguiu interpretar a resposta
        raise ValueError(
            "Não foi possível interpretar a resposta do AT+DETECT?.\n\nResposta completa:\n{}".format(raw)
        )

    return {
        "type": tipo or "",
        "id": sensor_id or "",
        "value": valor,
        "raw": raw,
    }
