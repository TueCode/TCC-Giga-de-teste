# ui/tabs/configure.py  (Python 3.6)
# -*- coding: utf-8 -*-
from __future__ import print_function

import os
import re
import json
import configparser
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

# Envia apenas AT; ID/MODEL/FW/HW/LOTE vêm da aba Status via 'state'
from communication import write_at_command

BASE_PADX = 12
BASE_PADY = 8


# ================== Tooltip simples (UX-6) ==================
class _Tooltip:
    """Tooltip que aparece após 600ms de hover sobre um widget."""
    def __init__(self, widget, text):
        self._widget = widget
        self._text   = text
        self._id     = None
        self._tip    = None
        widget.bind("<Enter>", self._schedule)
        widget.bind("<Leave>", self._cancel)
        widget.bind("<ButtonPress>", self._cancel)

    def _schedule(self, event=None):
        self._cancel()
        self._id = self._widget.after(600, self._show)

    def _cancel(self, event=None):
        if self._id:
            self._widget.after_cancel(self._id)
            self._id = None
        if self._tip:
            try:
                self._tip.destroy()
            except Exception:
                pass
            self._tip = None

    def _show(self):
        x = self._widget.winfo_rootx() + 20
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._tip = tw = tk.Toplevel(self._widget)
        tw.wm_overrideredirect(True)
        tw.wm_geometry("+{}+{}".format(x, y))
        lbl = tk.Label(tw, text=self._text, justify="left",
                       background="#ffffe0", relief="solid", borderwidth=1,
                       font=("TkDefaultFont", 9))
        lbl.pack(ipadx=4, ipady=2)

# === Registro (compatível com legado) ===
MANAGER_URL       = "https://manager.smetro.io"
LEGACY_TOKEN      = "67DAAE98ED0C612857A716202F463356FFCF1A018CE140AB4A4BEBC8EB274E6D"
LEGACY_PORT       = 2080
LEGACY_DOMAIN_WE  = "udp://manager.smetro.io"
LEGACY_DOMAIN_MB  = "manager.smetro.io"


# ================== Helpers ==================

def _validate_email(email):
    if not email:
        return False
    return re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email) is not None


def _map_protocol_code(proto_txt):
    p = (proto_txt or "").strip().lower()
    if p == "ubidots":   return "0"
    if p == "gh3":       return "1"
    if p == "sensorweb": return "2"
    return ""


def _load_legacy_ini(path):
    """
    Lê ini legado (seção DEFAULT). Retorna (dados_AT, meta_API).
    """
    cfg = configparser.ConfigParser()
    ok = cfg.read(path)
    if not ok or "DEFAULT" not in cfg:
        raise ValueError("Arquivo de configuração inválido ou vazio.")
    g = cfg["DEFAULT"]
    d = {
        "interface": g.get("interface", "wlan").strip().lower(),
        "dhcp":      g.get("dhcp", "1").strip(),
        "ssid":      g.get("ssid", "").strip(),
        "password":  g.get("password", "").strip(),
        "ip":        g.get("ip", "").strip(),
        "gateway":   g.get("gateway", "").strip(),
        "netmask":   g.get("netmask", "").strip(),
        "dns":       ",".join([x.strip() for x in g.get("dns","").split(",") if x.strip()]),
        "interval_powered": g.get("interval_powered", "").strip(),
        "interval_standby": g.get("interval_standby", "").strip(),
    }
    meta = {
        "username":         g.get("username", "").strip(),
        "protocol":         g.get("protocol", "").strip(),
        "protocol_code":    _map_protocol_code(g.get("protocol", "")),
        "hardware_version": g.get("hardware_version", "").strip(),
        "batch":            g.get("batch", "").strip(),
    }
    return d, meta


def _save_legacy_ini(path, d, meta):
    cfg = configparser.ConfigParser()
    cfg["DEFAULT"] = {}
    w = cfg["DEFAULT"]
    for k in ("interface","dhcp","ssid","password","ip","gateway","netmask","dns","interval_powered","interval_standby"):
        if k in d:
            w[k] = d.get(k, "")
    for k in ("username","protocol","hardware_version","batch"):
        if k in meta:
            w[k] = meta.get(k, "")
    with open(path, "w") as f:
        cfg.write(f)


def _apply_plan_to_device(port, plan, ui_root=None):
    """
    plan: dict nome -> (AT+CMD, value). Envia só valores não vazios.
    Retorna (oks, errs) com nomes (ex.: 'SSID','IP').
    """
    oks, errs = [], []
    for key, (cmd, value) in plan.items():
        try:
            if value is None:
                continue
            val = str(value)
            if val == "":
                continue
            sent = write_at_command(port, cmd, val)  # deve já conter delay interno
            (oks if sent else errs).append(key)
        except Exception:
            errs.append(key)
        try:
            if ui_root:
                ui_root.update()
        except Exception:
            pass
    return oks, errs


def _plan_from_form(interface, dhcp, ssid, password, ip, netmask, gateway, dns, powered, standby):
    """
    Constrói plano a partir dos valores da TELA (manual ou carregados).
    """
    plan = {}
    iface = (interface or "").strip().lower()
    dhcpv = (dhcp or "").strip()
    if iface in ("wlan","eth"):
        plan["CONN"] = ("AT+CONN", "0" if iface == "wlan" else "1")
    if iface == "wlan":
        if ssid:
            plan["SSID"]   = ("AT+SSID", ssid)
        if password:
            plan["PASSWD"] = ("AT+PASSWD", password)
    else:
        if dhcpv in ("0","1"):
            plan["DHCP"] = ("AT+DHCP", dhcpv)
        if dhcpv == "0":
            if ip:      plan["IP"]      = ("AT+IP", ip)
            if netmask: plan["NETMASK"] = ("AT+NETMASK", netmask)
            if gateway: plan["GATEWAY"] = ("AT+GATEWAY", gateway)
            if dns:     plan["DNS"]     = ("AT+DNS", dns)
    if (powered or "").strip() != "" or (standby or "").strip() != "":
        plan["INTERVAL"] = ("AT+INTERVAL", "{},{}".format(powered or "", standby or ""))
    return plan


def _plan_from_ini_all(d):
    """
    Constrói plano a partir do ARQUIVO, enviando tudo o que existir no arquivo.
    """
    plan = {}
    if d.get("interface") in ("wlan","eth"):
        plan["CONN"] = ("AT+CONN", "0" if d["interface"] == "wlan" else "1")
    if d.get("dhcp") in ("0","1"):
        plan["DHCP"] = ("AT+DHCP", d["dhcp"])
    if d.get("ssid"):     plan["SSID"]   = ("AT+SSID", d["ssid"])
    if d.get("password"): plan["PASSWD"] = ("AT+PASSWD", d["password"])
    if d.get("ip"):       plan["IP"]      = ("AT+IP", d["ip"])
    if d.get("netmask"):  plan["NETMASK"] = ("AT+NETMASK", d["netmask"])
    if d.get("gateway"):  plan["GATEWAY"] = ("AT+GATEWAY", d["gateway"])
    if d.get("dns"):      plan["DNS"]     = ("AT+DNS", d["dns"])
    pwr = d.get("interval_powered", ""); stb = d.get("interval_standby", "")
    if pwr != "" or stb != "":
        plan["INTERVAL"] = ("AT+INTERVAL", "{},{}".format(pwr, stb))
    return plan


def _proto_to_int(proto):
    """Mapeia protocolo para inteiro do legado: 0=Ubidots, 1=GH3, 2=Sensorweb."""
    if isinstance(proto, int):
        return max(0, min(2, proto))
    s = (proto or "").strip().lower()
    if s == "ubidots":
        return 0
    if s == "gh3":
        return 1
    if s == "sensorweb":
        return 2
    try:
        return max(0, min(2, int(s)))
    except Exception:
        return 1  # default GH3


def _build_legacy_payload(state, ini_data=None, ini_meta=None, username_override="", protocol_override=""):
    """
    Constrói (url, headers, data) exatamente como o LEGADO.
    - Usa ini_data/meta (arquivo carregado) se existirem; senão cai para UI/state.
    """
    dev_id = (getattr(state, "device_id", "") or "").strip()
    model  = (getattr(state, "device_model", "") or "").strip()
    if not dev_id:
        raise ValueError("ID do dispositivo não disponível (vá na aba Status e clique em Atualizar).")

    # URL com token na query (legado)
    url = "{}/devices/{}/create?token={}".format(MANAGER_URL, dev_id, LEGACY_TOKEN)

    # Modelo -> type/domain (legado)
    m = model.upper()
    if m == "MB":
        type_id = 2
        domain  = LEGACY_DOMAIN_MB
    else:
        # default WE
        type_id = 1
        domain  = LEGACY_DOMAIN_WE

    # username (email) e protocolo: arquivo > overrides > vazio
    username = ""
    proto    = ""
    if ini_meta:
        username = (ini_meta.get("username") or "").strip()
        proto    = (ini_meta.get("protocol") or "").strip()
    if username_override:
        username = username_override.strip()
    if protocol_override:
        proto = protocol_override.strip()
    proto_int = _proto_to_int(proto)

    # intervals — arquivo > state > default
    get_data = ""
    sleep_get_data = ""
    if ini_data:
        get_data       = (ini_data.get("interval_powered", "") or "").strip()
        sleep_get_data = (ini_data.get("interval_standby", "") or "").strip()
    if not get_data:
        get_data = str(getattr(state, "powered", 120) or 120)
    if not sleep_get_data:
        sleep_get_data = str(getattr(state, "standby", 600) or 600)

    # HW version e Lote — arquivo > state
    hw_version = ""
    lot = ""
    if ini_meta:
        hw_version = (ini_meta.get("hardware_version", "") or "").strip()
        lot        = (ini_meta.get("batch", "") or "").strip()
    if not hw_version:
        hw_version = str(getattr(state, "device_hw", "") or "")
    if not lot:
        lot = str(getattr(state, "device_lot", "") or "")

    # firmware_name no legado
    firmware_name = str(getattr(state, "device_fw", "") or "")

    headers = {
        "Content-Type": "application/json",
        "Accept": "text/plain",
    }

    # payload idêntico ao legado
    data = {
        "name": "",
        "get_data":       str(get_data),
        "sleep_get_data": str(sleep_get_data),
        "enable": 1,
        "type": type_id,
        "user_email": username,
        "domain": domain,
        "port": LEGACY_PORT,
        "iccid": "",
        "apn": "",
        "user": "",
        "pwd": "",
        "firmware_name": firmware_name,
        "endpoint_protocol": proto_int,
        "comments": "",
        "endpoint_url": "",
        "endpoint_token": "",
        "endpoint_user": "",
        "endpoint_pwd": "",
        "hardware_version": hw_version,
        "lot": lot,
        "user_comments": ""
    }
    return url, headers, data


class _RegistrationStateSnapshot(object):
    """Somente os dados necessários para manter um cadastro consistente."""
    pass


def _registration_state_snapshot(state):
    """
    Copia os dados usados no cadastro antes de iniciar a requisição em thread.
    Assim, uma troca de WE, um novo INI ou uma edição posterior não muda a
    requisição que o operador acabou de confirmar.
    """
    snapshot = _RegistrationStateSnapshot()
    for name in (
        "device_id", "device_model", "device_fw", "device_hw", "device_lot",
        "powered", "standby", "device_read_port", "device_read_generation",
    ):
        setattr(snapshot, name, getattr(state, name, ""))

    ini_data = getattr(state, "last_ini_data", None)
    ini_meta = getattr(state, "last_ini_meta", None)
    snapshot.last_ini_data = dict(ini_data) if isinstance(ini_data, dict) else ini_data
    snapshot.last_ini_meta = dict(ini_meta) if isinstance(ini_meta, dict) else ini_meta
    return snapshot


def _manager_preview(state, username="", protocol=""):
    """
    Retorna somente os campos exibíveis do payload legado, sem expor URL ou
    token. A prévia usa exatamente a mesma precedência do registro atual.
    """
    try:
        _url, _headers, data = _build_legacy_payload(
            state,
            username_override=username,
            protocol_override=protocol
        )
    except ValueError:
        return {}
    return {
        "device_id": (getattr(state, "device_id", "") or "").strip(),
        "model": (getattr(state, "device_model", "") or "").strip(),
        "firmware": (getattr(state, "device_fw", "") or "").strip(),
        "port": (getattr(state, "device_read_port", "") or "").strip(),
        "email": data.get("user_email", ""),
        "protocol": data.get("endpoint_protocol", ""),
        "hardware_version": data.get("hardware_version", ""),
        "lot": data.get("lot", ""),
        "interval_powered": data.get("get_data", ""),
        "interval_standby": data.get("sleep_get_data", ""),
    }


def register_manager(state, username, protocol):
    """
    Envia o registro exatamente como o LEGADO:
    POST /devices/<ID>/create?token=TOKEN_FIXO
    Body JSON com os mesmos campos do addDevice.
    """
    ini_data = getattr(state, "last_ini_data", None)
    ini_meta = getattr(state, "last_ini_meta", None)

    url, headers, data = _build_legacy_payload(
        state,
        ini_data=ini_data,
        ini_meta=ini_meta,
        username_override=username,
        protocol_override=protocol
    )

    if not data.get("user_email"):
        return False, "Informe o e-mail (username)."

    try:
        import requests
        r = requests.post(url, data=json.dumps(data), headers=headers, timeout=10)
        if r.status_code == 200:
            return True, "Device Registrado!"
        elif r.status_code == 405:
            return True, "Device already exists."
        else:
            return False, "Erro {}: {}".format(r.status_code, r.text[:300])
    except Exception as e:
        return False, "Falha na requisição: {}".format(e)


# ================ UI =================

def build_configure_tab(nb, state):
    tab = ttk.Frame(nb)
    nb.add(tab, text="Configurar")
    for i in range(10):
        tab.grid_columnconfigure(i, weight=1)

    # ---------- Arquivo ----------
    box_file = ttk.Labelframe(tab, text="Arquivo de configuração (legado)")
    box_file.grid(row=0, column=0, columnspan=10, sticky="nsew", padx=BASE_PADX, pady=BASE_PADY)
    for i in range(10):
        box_file.grid_columnconfigure(i, weight=1)

    path_var = tk.StringVar()
    ttk.Label(box_file, text="Arquivo (.ini/.cfg):").grid(row=0, column=0, sticky="e", padx=6, pady=6)
    ttk.Entry(box_file, textvariable=path_var).grid(row=0, column=1, columnspan=6, sticky="we", padx=6, pady=6)
    ttk.Button(box_file, text="Carregar…", command=lambda: _pick_and_fill(path_var, fill_from_ini)) \
        .grid(row=0, column=7, sticky="w", padx=6, pady=6)
    ttk.Button(box_file, text="Salvar…", command=lambda: _save_from_form(path_var, gather_form(), gather_meta())) \
        .grid(row=0, column=8, sticky="w", padx=6, pady=6)
    btn_aplicar_arquivo = ttk.Button(
        box_file, text="Aplicar arquivo", command=lambda: _aplicar_arquivo()
    )
    btn_aplicar_arquivo.grid(row=0, column=9, sticky="w", padx=6, pady=6)

    # ---------- Configurações ----------
    frame_cfg = ttk.Labelframe(tab, text="Configurações")
    frame_cfg.grid(row=1, column=0, columnspan=10, sticky="nsew", padx=BASE_PADX, pady=(0, BASE_PADY))
    for i in range(10):
        frame_cfg.grid_columnconfigure(i, weight=1)

    ttk.Label(frame_cfg, text="Interface:").grid(row=0, column=0, sticky="e", padx=6, pady=6)
    iface_var = tk.StringVar(value="wlan")
    cb_iface = ttk.Combobox(frame_cfg, textvariable=iface_var, state="readonly", values=("wlan", "eth"), width=10)
    cb_iface.grid(row=0, column=1, sticky="w", padx=6, pady=6)
    _Tooltip(cb_iface, "AT+CONN: 0=Wi-Fi, 1=Ethernet")

    ttk.Label(frame_cfg, text="SSID (Wi-Fi):").grid(row=0, column=2, sticky="e", padx=6, pady=6)
    ssid_var = tk.StringVar()
    ent_ssid = ttk.Entry(frame_cfg, textvariable=ssid_var, width=22)
    ent_ssid.grid(row=0, column=3, sticky="w", padx=6, pady=6)
    _Tooltip(ent_ssid, "AT+SSID: nome da rede Wi-Fi (case-sensitive)")

    ttk.Label(frame_cfg, text="PASSWD (Wi-Fi):").grid(row=0, column=4, sticky="e", padx=6, pady=6)
    pwd_var = tk.StringVar()
    ent_pwd = ttk.Entry(frame_cfg, textvariable=pwd_var, width=22)
    ent_pwd.grid(row=0, column=5, sticky="w", padx=6, pady=6)
    _Tooltip(ent_pwd, "AT+PASSWD: senha da rede Wi-Fi")

    ttk.Label(frame_cfg, text="DHCP (Ethernet):").grid(row=1, column=0, sticky="e", padx=6, pady=6)
    dhcp_var = tk.StringVar(value="1")
    cb_dhcp = ttk.Combobox(frame_cfg, textvariable=dhcp_var, state="readonly", values=("1", "0"), width=10)
    cb_dhcp.grid(row=1, column=1, sticky="w", padx=6, pady=6)
    _Tooltip(cb_dhcp, "AT+DHCP: 1=automático, 0=IP fixo")

    ttk.Label(frame_cfg, text="IP (ETH):").grid(row=1, column=2, sticky="e", padx=6, pady=6)
    ip_var = tk.StringVar()
    ent_ip = ttk.Entry(frame_cfg, textvariable=ip_var, width=16)
    ent_ip.grid(row=1, column=3, sticky="w", padx=6, pady=6)
    _Tooltip(ent_ip, "AT+IP: endereço IP fixo (ex: 192.168.1.100)")

    ttk.Label(frame_cfg, text="NETMASK (ETH):").grid(row=1, column=4, sticky="e", padx=6, pady=6)
    mask_var = tk.StringVar()
    ent_mask = ttk.Entry(frame_cfg, textvariable=mask_var, width=16)
    ent_mask.grid(row=1, column=5, sticky="w", padx=6, pady=6)
    _Tooltip(ent_mask, "AT+NETMASK: máscara de sub-rede (ex: 255.255.255.0)")

    ttk.Label(frame_cfg, text="GATEWAY (ETH):").grid(row=2, column=2, sticky="e", padx=6, pady=6)
    gw_var = tk.StringVar()
    ent_gw = ttk.Entry(frame_cfg, textvariable=gw_var, width=16)
    ent_gw.grid(row=2, column=3, sticky="w", padx=6, pady=6)
    _Tooltip(ent_gw, "AT+GATEWAY: IP do gateway padrão")

    ttk.Label(frame_cfg, text="DNS 1,2 (ETH):").grid(row=2, column=4, sticky="e", padx=6, pady=6)
    dns_var = tk.StringVar()
    ent_dns = ttk.Entry(frame_cfg, textvariable=dns_var, width=16)
    ent_dns.grid(row=2, column=5, sticky="w", padx=6, pady=6)
    _Tooltip(ent_dns, "AT+DNS: um ou dois IPs separados por vírgula (ex: 8.8.8.8,8.8.4.4)")

    ttk.Label(frame_cfg, text="INTERVAL POWERED (s):").grid(row=3, column=0, sticky="e", padx=6, pady=6)
    pwr_var = tk.StringVar()
    ent_pwr = ttk.Entry(frame_cfg, textvariable=pwr_var, width=10)
    ent_pwr.grid(row=3, column=1, sticky="w", padx=6, pady=6)
    _Tooltip(ent_pwr, "AT+INTERVAL (powered): intervalo em segundos quando alimentado (mín: 1)")

    ttk.Label(frame_cfg, text="INTERVAL STANDBY (s):").grid(row=3, column=2, sticky="e", padx=6, pady=6)
    stb_var = tk.StringVar()
    ent_stb = ttk.Entry(frame_cfg, textvariable=stb_var, width=10)
    ent_stb.grid(row=3, column=3, sticky="w", padx=6, pady=6)
    _Tooltip(ent_stb, "AT+INTERVAL (standby): intervalo em segundos no modo economia (mín: 1)")

    btn_aplicar = ttk.Button(frame_cfg, text="Aplicar", command=lambda: _aplicar_unificado())
    btn_aplicar.grid(row=4, column=0, sticky="w", padx=6, pady=(6, 6))

    # ---------- Registrar na Manager ----------
    box_reg = ttk.Labelframe(tab, text="Registrar na Manager (Cloud)")
    box_reg.grid(row=2, column=0, columnspan=10, sticky="nsew", padx=BASE_PADX, pady=(0, BASE_PADY))
    for i in range(10):
        box_reg.grid_columnconfigure(i, weight=1)

    manager_device_var = tk.StringVar(value="WE para cadastro: leia o dispositivo na aba Status.")
    manager_payload_var = tk.StringVar(value="")
    manager_source_var = tk.StringVar(value="")
    manager_result_var = tk.StringVar(value="Aguardando uma WE lida nesta sessão.")

    ttk.Label(
        box_reg, textvariable=manager_device_var, font=("TkDefaultFont", 10, "bold")
    ).grid(row=0, column=0, columnspan=10, sticky="w", padx=6, pady=(8, 2))
    ttk.Label(
        box_reg, textvariable=manager_payload_var, foreground="#245a87",
        wraplength=820, justify="left"
    ).grid(row=1, column=0, columnspan=10, sticky="w", padx=6, pady=2)
    ttk.Label(
        box_reg, textvariable=manager_source_var, foreground="#666",
        wraplength=820, justify="left"
    ).grid(row=2, column=0, columnspan=10, sticky="w", padx=6, pady=(2, 8))

    ttk.Separator(box_reg, orient="horizontal").grid(
        row=3, column=0, columnspan=10, sticky="ew", padx=6, pady=(0, 4)
    )

    ttk.Label(box_reg, text="Username (e-mail):").grid(row=4, column=0, sticky="e", padx=6, pady=6)
    user_var = tk.StringVar()
    ent_user = ttk.Entry(box_reg, textvariable=user_var, width=28)
    ent_user.grid(row=4, column=1, sticky="w", padx=6, pady=6)

    ttk.Label(box_reg, text="Protocolo:").grid(row=4, column=2, sticky="e", padx=6, pady=6)
    proto_var = tk.StringVar()
    cb_proto = ttk.Combobox(box_reg, textvariable=proto_var, state="readonly",
                            values=("GH3", "Ubidots", "Sensorweb"), width=14)
    cb_proto.grid(row=4, column=3, sticky="w", padx=6, pady=6)

    ttk.Label(box_reg, text="HW version:").grid(row=5, column=0, sticky="e", padx=6, pady=6)
    hwv_var = tk.StringVar()
    ent_hwv = ttk.Entry(box_reg, textvariable=hwv_var, width=14)
    ent_hwv.grid(row=5, column=1, sticky="w", padx=6, pady=6)

    ttk.Label(box_reg, text="Batch:").grid(row=5, column=2, sticky="e", padx=6, pady=6)
    batch_var = tk.StringVar()
    ent_batch = ttk.Entry(box_reg, textvariable=batch_var, width=14)
    ent_batch.grid(row=5, column=3, sticky="w", padx=6, pady=6)

    hint = ttk.Label(
        box_reg,
        foreground="#666",
        text="O resumo mostra os valores efetivos do cadastro conforme a regra atual do legado."
    )
    hint.grid(row=7, column=0, columnspan=10, sticky="w", padx=6, pady=(2, 6))

    btn_registrar = ttk.Button(box_reg, text="Registrar na Manager", command=lambda: _registrar_manager())
    btn_registrar.grid(row=6, column=0, sticky="w", padx=6, pady=(6, 2))
    ttk.Label(
        box_reg, textvariable=manager_result_var, foreground="#444",
        wraplength=700, justify="left"
    ).grid(row=6, column=1, columnspan=9, sticky="w", padx=6, pady=(6, 2))

    # ======= Funções internas =======

    def _set_vis(widget, show):
        try:
            if show:
                widget.grid()
            else:
                widget.grid_remove()
        except Exception:
            pass

    def _update_visibility(*_):
        iface = iface_var.get()
        is_wifi = (iface == "wlan")
        is_eth  = (iface == "eth")
        _set_vis(ent_ssid, is_wifi)
        _set_vis(ent_pwd, is_wifi)
        _set_vis(cb_dhcp, is_eth)
        d = dhcp_var.get()
        show_ip = is_eth and (d == "0")
        for w in (ent_ip, ent_mask, ent_gw, ent_dns):
            _set_vis(w, show_ip)

    def gather_form():
        return {
            "interface": iface_var.get().strip(),
            "dhcp":      dhcp_var.get().strip(),
            "ssid":      ssid_var.get().strip(),
            "password":  pwd_var.get().strip(),
            "ip":        ip_var.get().strip(),
            "netmask":   mask_var.get().strip(),
            "gateway":   gw_var.get().strip(),
            "dns":       dns_var.get().strip(),
            "interval_powered": pwr_var.get().strip(),
            "interval_standby": stb_var.get().strip(),
        }

    def gather_meta():
        return {
            "username":         user_var.get().strip(),
            "protocol":         proto_var.get().strip(),
            "protocol_code":    _map_protocol_code(proto_var.get()),
            "hardware_version": hwv_var.get().strip(),
            "batch":            batch_var.get().strip(),
        }

    operation_state = {"apply": False, "register": False}

    def _is_current_device_read():
        return (
            bool(getattr(state, "selected_port", None)) and
            bool(getattr(state, "device_id", "")) and
            getattr(state, "device_read_port", None) == state.selected_port and
            getattr(state, "device_read_generation", None) ==
                getattr(state, "connection_generation", None)
        )

    def _refresh_manager_context(*_):
        preview_state = _registration_state_snapshot(state)
        preview_state.device_hw = hwv_var.get().strip()
        preview_state.device_lot = batch_var.get().strip()
        preview = _manager_preview(
            preview_state, user_var.get().strip(), proto_var.get().strip()
        )
        if not preview or not _is_current_device_read():
            manager_device_var.set(
                "WE para cadastro: leia o dispositivo na aba Status nesta sessão."
            )
            manager_payload_var.set("")
            manager_source_var.set(
                "O cadastro será habilitado após uma leitura válida da WE conectada."
            )
            if not operation_state["register"]:
                manager_result_var.set("Aguardando uma WE lida nesta sessão.")
            return

        manager_device_var.set(
            "WE selecionada: ID {}  |  Modelo {}  |  FW {}  |  Porta {}".format(
                preview["device_id"] or "-",
                preview["model"] or "-",
                preview["firmware"] or "-",
                preview["port"] or state.selected_port or "-"
            )
        )
        protocol_label = {
            "0": "Ubidots", "1": "GH3", "2": "Sensorweb"
        }.get(str(preview["protocol"]), str(preview["protocol"]) or "-")
        manager_payload_var.set(
            "Dados efetivos: e-mail {}  |  protocolo {}  |  HW {}  |  lote {}"
            "  |  intervalos {}s / {}s".format(
                preview["email"] or "-",
                protocol_label,
                preview["hardware_version"] or "-",
                preview["lot"] or "-",
                preview["interval_powered"] or "-",
                preview["interval_standby"] or "-"
            )
        )
        if getattr(state, "last_ini_data", None):
            filename = os.path.basename(path_var.get() or "arquivo carregado")
            manager_source_var.set(
                "Origem: {}. O resumo já considera as prioridades do cadastro legado."
                .format(filename)
            )
        else:
            manager_source_var.set(
                "Origem: campos da tela e valores padrão do cadastro legado."
            )
        if not operation_state["register"]:
            manager_result_var.set("Pronto para registrar esta WE.")

    def fill_from_ini(path):
        try:
            d, meta = _load_legacy_ini(path)
        except Exception as e:
            messagebox.showerror("Arquivo", "Falha ao carregar:\n{}".format(e))
            return
        path_var.set(path)

        iface_var.set(d.get("interface", "wlan"))
        dhcp_var.set(d.get("dhcp", "1"))
        ssid_var.set(d.get("ssid", ""))
        pwd_var.set(d.get("password", ""))
        ip_var.set(d.get("ip", ""))
        mask_var.set(d.get("netmask", ""))
        gw_var.set(d.get("gateway", ""))
        dns_var.set(d.get("dns", ""))
        pwr_var.set(d.get("interval_powered", ""))
        stb_var.set(d.get("interval_standby", ""))
        _update_visibility()

        user_var.set(meta.get("username", ""))
        proto = meta.get("protocol", "")
        if proto.lower() in ("gh3", "ubidots", "sensorweb"):
            proto_var.set("Sensorweb" if proto.lower() == "sensorweb" else proto.upper())
        else:
            proto_var.set("")
        hwv_var.set(meta.get("hardware_version", ""))
        batch_var.set(meta.get("batch", ""))

        # Guarda no state para o registro igual ao legado
        try:
            state.last_ini_data = d
            state.last_ini_meta = meta
        except Exception:
            pass

        _refresh_manager_context()
        messagebox.showinfo("OK", "Arquivo carregado e campos preenchidos.")

    def _pick_and_fill(var, cb):
        p = filedialog.askopenfilename(
            title="Selecione o arquivo de configuração",
            filetypes=[("Config legado", "*.ini *.cfg *.txt"), ("Todos", "*.*")]
        )
        if p:
            var.set(p)
            cb(p)

    def _save_from_form(var, d, meta):
        p = filedialog.asksaveasfilename(
            title="Salvar configuração",
            defaultextension=".ini",
            filetypes=[("Config legado", "*.ini"), ("Todos", "*.*")]
        )
        if not p:
            return
        try:
            _save_legacy_ini(p, d, meta)
            var.set(p)
            messagebox.showinfo("Salvar", "Arquivo salvo:\n{}".format(p))
        except Exception as e:
            messagebox.showerror("Salvar", "Falha ao salvar:\n{}".format(e))

    def _run_apply_operation(title, plan):
        """
        Mantém plano, ordem e comandos AT existentes. Apenas deixa a interface
        livre enquanto a sequência já definida é enviada.
        """
        port = state.selected_port
        generation = state.connection_generation
        operation_state["apply"] = True
        _update_enabled()
        state.show_busy(title)

        def worker():
            try:
                oks, errs = _apply_plan_to_device(port, plan)
                error = ""
            except Exception as e:
                oks, errs = [], []
                error = str(e)

            def finish():
                operation_state["apply"] = False
                if not state.is_current_session(port, generation):
                    return
                state.hide_busy()
                _update_enabled()
                if error:
                    messagebox.showerror("Aplicar", "Falha ao aplicar:\n{}".format(error))
                    return
                messagebox.showinfo(
                    "Resultado",
                    "{}\n\nAT enviados: {}\nOK : {}\nERRO: {}\n".format(
                        title,
                        len(plan),
                        ", ".join(oks) if oks else "-",
                        ", ".join(errs) if errs else "-"
                    )
                )

            state.root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def _aplicar_unificado():
        if not state.selected_port:
            messagebox.showwarning("Aplicar", "Conecte a uma porta primeiro.")
            return
        f = gather_form()
        plan = _plan_from_form(
            f.get("interface"), f.get("dhcp"),
            f.get("ssid"), f.get("password"),
            f.get("ip"), f.get("netmask"), f.get("gateway"), f.get("dns"),
            f.get("interval_powered"), f.get("interval_standby")
        )
        if not plan:
            messagebox.showinfo("Aplicar", "Nenhum campo preenchido para enviar.")
            return
        # UX-7: confirmarção com resumo
        resumo = "\n".join("  • {} = {}".format(k, v) for k, (_, v) in plan.items())
        if not messagebox.askokcancel("Confirmar",
                "Serão enviados os seguintes AT commands:\n\n{}\n\nConfirma?".format(resumo)):
            return
        _run_apply_operation("Aplicando configurações...", plan)

    def _aplicar_arquivo():
        if not state.selected_port:
            messagebox.showwarning("Aplicar arquivo", "Conecte a uma porta primeiro.")
            return
        path = (path_var.get() or "").strip()
        if not path:
            messagebox.showwarning("Aplicar arquivo", "Selecione e carregue um arquivo primeiro.")
            return
        try:
            d, _meta = _load_legacy_ini(path)
        except Exception as e:
            messagebox.showerror("Aplicar arquivo", "Falha ao ler arquivo:\n{}".format(e))
            return
        plan = _plan_from_ini_all(d)
        if not plan:
            messagebox.showinfo("Aplicar arquivo", "Nenhum campo encontrado no arquivo.")
            return
        # UX-7: confirmação com resumo
        resumo = "\n".join("  • {} = {}".format(k, v) for k, (_, v) in plan.items())
        if not messagebox.askokcancel("Confirmar arquivo",
                "Serão enviados os seguintes AT commands:\n\n{}\n\nConfirma?".format(resumo)):
            return
        _run_apply_operation("Aplicando arquivo...", plan)

    def _registrar_manager():
        """Registra o snapshot atual sem travar a interface."""
        if operation_state["apply"] or operation_state["register"]:
            return
        if not state.selected_port:
            messagebox.showwarning("Registrar", "Conecte a uma porta primeiro.")
            return

        if not _is_current_device_read():
            messagebox.showwarning(
                "Registrar",
                "Leia a WE atual na aba Status antes de registrar."
            )
            return

        username = user_var.get().strip()
        protocol = proto_var.get().strip()
        registration_state = _registration_state_snapshot(state)
        registration_state.device_hw = hwv_var.get().strip()
        registration_state.device_lot = batch_var.get().strip()
        _refresh_manager_context()
        port = state.selected_port
        generation = state.connection_generation
        device_id = registration_state.device_id
        operation_state["register"] = True
        manager_result_var.set("Registrando a WE {} na Manager...".format(device_id))
        _update_enabled()
        state.show_busy("Registrando na Manager...")

        def worker():
            try:
                ok, msg = register_manager(registration_state, username, protocol)
            except Exception as e:
                ok, msg = False, "Falha no cadastro: {}".format(e)

            def finish():
                operation_state["register"] = False
                if not state.is_current_session(port, generation):
                    return
                state.hide_busy()
                _refresh_manager_context()
                _update_enabled()
                if ok:
                    manager_result_var.set(
                        "Cadastro da WE {} concluído: {}".format(device_id, msg)
                    )
                    messagebox.showinfo("Registrar", "OK\n{}".format(msg))
                else:
                    manager_result_var.set(
                        "Cadastro da WE {} não foi concluído: {}".format(device_id, msg)
                    )
                    messagebox.showerror("Registrar", "ERRO\n{}".format(msg))

            state.root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    cb_iface.bind("<<ComboboxSelected>>", _update_visibility)
    cb_dhcp.bind("<<ComboboxSelected>>", _update_visibility)
    _update_visibility()

    # Atualiza botões com estado de conexão
    def _update_enabled(*_):
        connected = bool(getattr(state, "selected_port", None))
        operation_active = operation_state["apply"] or operation_state["register"]
        for w in (btn_aplicar, btn_aplicar_arquivo):
            try:
                w.configure(
                    state=("normal" if connected and not operation_active else "disabled")
                )
            except Exception:
                pass
        try:
            btn_registrar.configure(
                state=(
                    "normal"
                    if connected and _is_current_device_read() and not operation_active
                    else "disabled"
                )
            )
        except Exception:
            pass
        _refresh_manager_context()

    tab.bind("<<ConnectionChanged>>", lambda e: _update_enabled())
    tab.bind("<Visibility>",          lambda e: _update_enabled())
    user_var.trace("w", _refresh_manager_context)
    proto_var.trace("w", _refresh_manager_context)
    hwv_var.trace("w", _refresh_manager_context)
    batch_var.trace("w", _refresh_manager_context)
    _update_enabled()

    return tab
