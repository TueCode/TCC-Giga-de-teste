# smetro_printer.py
# Impressão de etiquetas via lp e CUPS (modo RAW)

import subprocess

# Filas padrão no CUPS (ajuste os nomes com 'lpstat -p')
CUPS_QUEUE_WE     = "ZTC-GC420t--EPL-"         # impressora usada para etiqueta da WE
CUPS_QUEUE_SENSOR = "ZTC-ZD220-203dpi-ZPL"     # impressora usada para sensores
CUPS_QUEUE_THM    = "ZTC-ZD220-203dpi-ZPL"     # impressora usada para THM

# Código ANATEL padrão (WE)
ANATEL_CODE_DEFAULT = "16938-23-13721"


# =====================================================
# ETIQUETA DA WE (DISPOSITIVO)
# =====================================================

def _zpl_label(device_id, model, hw_version="", manufacturing_lot="", anatel_code=ANATEL_CODE_DEFAULT):
    """
    Gera a etiqueta SM-WE no layout:

    ID: <device_id>
    [barcode do ID]
    MODELO:SM<model>        FABRICADO NO BRASIL
    VERSÃO HW:<hw>   LOTE:<lot>   ANATEL:<anatel_code>
    """
    manufacturing_lot = manufacturing_lot or "-"
    hw_version = hw_version or "-"
    anatel_code = anatel_code or (ANATEL_CODE_DEFAULT or "-")
    model = model or "-"

    return (
        "^CT~~CD,~CC^~CT~\r\n"
        "^XA~TA000~JSN^LT0^MNW^MTT^PON^PMN^LH0,0^JMA^JUS^LRN^CI0^XZ\r\n"
        "^XA\r\n"
        "^CI28\r\n"
        "^MMT\r\n"
        "^PW600\r\n"
        "^LL0200\r\n"
        "^LS0\r\n"

        # Linha 1 – ID em texto grande
        "^FT40,40^A0N,30,28^FH\\^FDID:" + str(device_id) + "^FS\r\n"

        # Linha 2 – código de barras do ID
        "^BY2,3,60\r\n"
        "^FT40,90^BCN,60,N,N,N\r\n"
        "^FD>" + str(device_id) + "^FS\r\n"

        # Linha 3 – MODELO e FABRICADO NO BRASIL
        "^FT40,135^A0N,22,20^FH\\^FDMODELO:SM" + str(model) + "^FS\r\n"
        "^FT360,135^A0N,22,20^FH\\^FDFABRICADO NO BRASIL^FS\r\n"

        # Linha 4 – VERSÃO HW, LOTE, ANATEL
        "^FT40,165^A0N,22,20^FH\\^FDVERSÃO HW:" + str(hw_version) + "^FS\r\n"
        "^FT240,165^A0N,22,20^FH\\^FDLOTE:" + str(manufacturing_lot) + "^FS\r\n"
        "^FT430,165^A0N,22,20^FH\\^FDANATEL:" + str(anatel_code) + "^FS\r\n"

        "^PQ1,0,1,Y^XZ\r\n"
    )


def print_label(model, device_id, hw_version="", lot="", printer_name=None):
    """
    Envia a etiqueta ZPL da WE via CUPS em modo RAW (pass-through).
    Usa por padrão a fila CUPS_QUEUE_WE.
    """
    queue = printer_name or CUPS_QUEUE_WE

    if not str(model).strip() or not str(device_id).strip():
        raise ValueError("MODEL e ID são obrigatórios para imprimir etiqueta.")

    zpl = _zpl_label(
        device_id=device_id,
        model=model,
        hw_version=hw_version,
        manufacturing_lot=lot
    )

    try:
        subprocess.run(
            ["lp", "-d", queue, "-o", "raw"],
            input=zpl.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True
        )
        return True
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or b"").decode("utf-8", errors="ignore")
        raise RuntimeError("Erro ao imprimir na fila {}: {}".format(queue, msg))


# =====================================================
# ETIQUETA THM
# =====================================================

def _zpl_thm_label(device_id, model, hw_version="", manufacturing_lot=""):
    """
    Gera a etiqueta THM baseada no padrão THM Sensorweb.

    Neste layout:
        - device_id -> ID principal / conteúdo do QR
        - model -> nome/modelo do sensor
        - lot -> lote
        - a linha '1.1V | 49F5BA3A' é fixa
        - hw_version é ignorado para manter compatibilidade da chamada
    """
    device_id          = str(device_id or "").strip() or "-"
    model              = str(model or "").strip() or "-"
    manufacturing_lot  = str(manufacturing_lot or "").strip() or "-"

    return (
        "^CT~~CD,~CC^~CT~\r\n"
        "^XA~TA000~JSN^LT0^MNW^MTT^PON^PMN^LH0,0^JMA^PR2,2~SD20^JUS^LRN^CI0^XZ\r\n"
        "^XA\r\n"
        "^CI28\r\n"
        "^MMT\r\n"
        "^PW320\r\n"
        "^LL0144\r\n"
        "^LS0\r\n"

        # QR Code
        "^FT16,128^BQN,2,4\r\n"
        "^FH\\^FDLA," + device_id + "^FS\r\n"

        # Texto vertical lateral fixo
        "^FT245,19^A0R,20,19^FB119,1,0,C^FH\\^FDTemperatura^FS\r\n"
        "^FT221,19^A0R,20,19^FB119,1,0,C^FH\\^FDUmidade^FS\r\n"
        "^FT292,19^A0R,20,21^FH\\^FDSENSORWEB^FS\r\n"

        # Linha inferior fixa
        "^FT136,135^A0B,17,16^FH\\^FD1.1V | 49F5BA3A^FS\r\n"

        # ID principal
        "^FT119,141^A0B,16,19^FB132,1,0,C^FH\\^FD" + device_id + "^FS\r\n"

        # Modelo vertical
        "^FT268,29^A0R,17,16^FB95,1,0,C^FH\\^FD" + model + "^FS\r\n"

        # Lote
        "^FT16,30^A0N,14,16^FH\\^FDLOTE " + manufacturing_lot + "^FS\r\n"

        "^PQ1,0,1,Y^XZ\r\n"
    )


def print_thm_label(model, device_id, hw_version="", lot="", printer_name=None):
    """
    Imprime a etiqueta THM usando as MESMAS variáveis da WE:
        model, device_id, hw_version, lot

    Observação:
        hw_version é mantido apenas por compatibilidade, mas não é usado,
        porque a linha inferior da THM é fixa.
    """
    queue = printer_name or CUPS_QUEUE_THM

    if not str(model).strip() or not str(device_id).strip():
        raise ValueError("MODEL e ID são obrigatórios para imprimir etiqueta THM.")

    zpl = _zpl_thm_label(
        device_id=device_id,
        model=model,
        hw_version=hw_version,
        manufacturing_lot=lot
    )

    try:
        subprocess.run(
            ["lp", "-d", queue, "-o", "raw"],
            input=zpl.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True
        )
        return True
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or b"").decode("utf-8", errors="ignore")
        raise RuntimeError("Erro ao imprimir etiqueta THM na fila {}: {}".format(queue, msg))


# =====================================================
# ETIQUETA DE SENSOR (PADRÃO SENSORWEB - SHT31)
# =====================================================

def _split_id_for_two_lines(sensor_id):
    """
    Quebra o ID em duas linhas, igual ao padrão da Sensorweb.
    Ex.: 11653266175168514 -> 116532661 / 75168514
    """
    if not sensor_id:
        return ("", "")

    s = "".join(ch for ch in str(sensor_id).strip() if ch.isdigit())
    if not s:
        # fallback para IDs alfanuméricos
        s = str(sensor_id).strip()

    mid = (len(s) + 1) // 2
    return s[:mid], s[mid:]


def _zpl_sensor_label(sensor_id, sensor_type, lot,
                      client_name=None, measure_label=None):
    """
    Gera a etiqueta de SENSOR no padrão do arquivo
    'Etiqueta SENSOR SHT 31 SENSORWEB.prn'.

    Mapeamento:
      - sensor_id   -> conteúdo do QR e ID em 2 linhas
      - sensor_type -> modelo vertical (ex.: SHT-31)
      - lot         -> Lote impresso
      - client_name -> mantido por compatibilidade de API; não usado no layout
      - measure_label -> mantido por compatibilidade de API; layout é fixo:
                         Temperatura / Umidade / SENSORWEB
    """
    sensor_id   = str(sensor_id or "").strip() or "-"
    sensor_type = str(sensor_type or "").strip() or "-"
    lot         = str(lot or "").strip() or "-"
    id_line1, id_line2 = _split_id_for_two_lines(sensor_id)

    return (
        "^CT~~CD,~CC^~CT~\r\n"
        "^XA~TA000~JSN^LT0^MNW^MTT^PON^PMN^LH0,0^JMA^PR2,2~SD20^JUS^LRN^CI0^XZ\r\n"
        "^XA\r\n"
        "^CI28\r\n"
        "^MMT\r\n"
        "^PW320\r\n"
        "^LL0144\r\n"
        "^LS0\r\n"

        # QR Code
        "^FT12,138^BQN,2,4\r\n"
        "^FH\\^FDLA," + sensor_id + "^FS\r\n"

        # Textos verticais fixos
        "^FT236,20^A0R,20,19^FB119,1,0,C^FH\\^FDTemperatura^FS\r\n"
        "^FT212,20^A0R,20,19^FB119,1,0,C^FH\\^FDUmidade^FS\r\n"
        "^FT288,10^A0R,20,24^FH\\^FDSENSORWEB^FS\r\n"

        # Lote
        "^FT12,34^A0N,20,19^FH\\^FDLote " + lot + "^FS\r\n"

        # ID em 2 linhas
        "^FT118,130^A0B,18,21^FB90,1,0,C^FH\\^FD" + id_line1 + "^FS\r\n"
        "^FT140,130^A0B,18,21^FB90,1,0,C^FH\\^FD" + id_line2 + "^FS\r\n"

        # Modelo
        "^FT264,44^A0R,17,16^FB71,1,0,C^FH\\^FD" + sensor_type + "^FS\r\n"

        "^PQ1,0,1,Y^XZ\r\n"
    )


def print_sensor_label(sensor_id,
                       sensor_type,
                       client_name,
                       lot,
                       measure_label="TEMPERATURA & UMIDADE",
                       printer_name=None):
    """
    Imprime a etiqueta de SENSOR no padrão Sensorweb SHT31.
    client_name e measure_label são mantidos por compatibilidade de API,
    mas o layout ZPL é fixo (Temperatura / Umidade / SENSORWEB).
    """
    queue = printer_name or CUPS_QUEUE_SENSOR

    if not str(sensor_id).strip():
        raise ValueError("sensor_id é obrigatório para imprimir etiqueta de sensor.")

    zpl = _zpl_sensor_label(
        sensor_id=sensor_id,
        sensor_type=sensor_type,
        lot=lot,
        client_name=client_name,
        measure_label=measure_label,
    )

    try:
        subprocess.run(
            ["lp", "-d", queue, "-o", "raw"],
            input=zpl.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True
        )
        return True
    except subprocess.CalledProcessError as e:
        msg = (e.stderr or b"").decode("utf-8", errors="ignore")
        raise RuntimeError("Erro ao imprimir etiqueta de sensor na fila {}: {}".format(queue, msg))


# =====================================================
# UTILIDADES
# =====================================================

def list_printers():
    """
    Retorna a lista de impressoras conhecidas pelo CUPS.
    """
    try:
        result = subprocess.run(
            ["lpstat", "-p"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
            text=True
        )
        printers = []
        for line in result.stdout.splitlines():
            if line.startswith("printer "):
                printers.append(line.split()[1])
        return printers
    except Exception:
        return []