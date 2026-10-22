# app.py  (Python 3.6)
# -*- coding: utf-8 -*-
from __future__ import print_function
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox

ROOT = os.path.dirname(os.path.abspath(__file__))
TABS_DIR = os.path.join(ROOT, "ui", "tabs")
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)
if TABS_DIR not in sys.path:
    sys.path.insert(0, TABS_DIR)

try:
    import status as status_tab
except Exception:
    status_tab = None
try:
    import configure as configure_tab
except Exception:
    configure_tab = None
try:
    import firmware as firmware_tab
except Exception:
    firmware_tab = None

try:
    from ui.style import setup_style
except Exception:
    setup_style = None

# Comunicação com a WE
try:
    from communication import list_ports, test_connection, test_device, write_at_command, detect_sensor
except Exception:
    def list_ports():
        return []
    def test_connection(_p):
        return False
    def test_device(_p):
        return {}
    def write_at_command(_p, _c, _v):
        return False
    def detect_sensor(_p, *args, **kwargs):
        raise RuntimeError("Função detect_sensor indisponível.")

# Impressão de etiquetas de sensor
try:
    from smetro_printer import print_sensor_label
except Exception:
    def print_sensor_label(*_args, **_kwargs):
        raise RuntimeError("Função print_sensor_label indisponível.")


# ---------------- Busy (carregando) ----------------
class BusyDialog(tk.Toplevel):
    def __init__(self, master, message="Processando..."):
        tk.Toplevel.__init__(self, master)
        self.title("Aguarde")
        self.resizable(False, False)
        self.transient(master)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", lambda: None)  # não deixa fechar
        frm = ttk.Frame(self, padding=12)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=message).pack(pady=(0,8))
        self.pb = ttk.Progressbar(frm, mode="indeterminate", length=260)
        self.pb.pack()
        try:
            self.pb.start(12)
        except Exception:
            pass
        self.update_idletasks()
        # centralizar
        try:
            self.geometry("+%d+%d" % (master.winfo_rootx() + master.winfo_width()//2 - 160,
                                      master.winfo_rooty() + master.winfo_height()//2 - 40))
        except Exception:
            pass

    def close(self):
        try:
            self.pb.stop()
        except Exception:
            pass
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()


# ===================== Estado =====================
class AppState(object):
    def __init__(self):
        self.selected_port = None
        self.device_id = ""
        self.device_model = ""
        self.device_fw = ""
        self.device_hw = ""
        self.device_lot = ""
        self.device_read_port = None
        self.device_read_generation = None
        self.connection_generation = 0
        self.last_ini_data = None
        self.last_ini_meta = None
        self.last_ports = []
        self.root = None
        self._busy = None
        self.on_device_read = None

    def begin_session(self, port):
        """Inicia uma sessão visual nova, sem reutilizar dados da WE anterior."""
        self.connection_generation += 1
        self.selected_port = port
        self.clear_session_data()

    def end_session(self):
        """Encerra a sessão visual atual e invalida leituras pendentes."""
        self.connection_generation += 1
        self.selected_port = None
        self.clear_session_data()
        self.hide_busy()

    def clear_session_data(self):
        self.device_id = ""
        self.device_model = ""
        self.device_fw = ""
        self.device_hw = ""
        self.device_lot = ""
        self.device_read_port = None
        self.device_read_generation = None
        # A aba é recriada após desconectar. Não mantemos um INI invisível
        # que possa afetar o cadastro da próxima WE.
        self.last_ini_data = None
        self.last_ini_meta = None

    def is_current_session(self, port, generation):
        return (
            bool(port) and
            self.selected_port == port and
            self.connection_generation == generation
        )

    def update_from_read(self, d, port=None, generation=None):
        """
        Atualiza somente a sessão que originou a leitura.
        Retorna False quando a resposta chegou depois de desconectar ou trocar
        de porta, evitando repintar a tela com dados antigos.
        """
        if not isinstance(d, dict):
            return False
        if port is not None and generation is not None:
            if not self.is_current_session(port, generation):
                return False

        self.device_id = d.get("ID", self.device_id)
        self.device_model = d.get("MODEL", self.device_model)
        self.device_fw = d.get("VERSION", self.device_fw)
        self.device_hw = d.get("HW", self.device_hw)
        self.device_lot = d.get("LOT", self.device_lot)
        self.device_read_port = port or self.selected_port
        self.device_read_generation = (
            generation if generation is not None else self.connection_generation
        )

        callback = self.on_device_read
        if callable(callback):
            callback()
        return True

    # Busy helpers (usados pelas abas)
    def show_busy(self, message="Processando..."):
        try:
            if self._busy is None and self.root:
                self._busy = BusyDialog(self.root, message)
                self.root.update_idletasks()
        except Exception:
            self._busy = None

    def hide_busy(self):
        if self._busy:
            try:
                self._busy.close()
            except Exception:
                pass
            self._busy = None


# ===================== App =====================
REFRESH_MS = 2000  # monitora portas a cada 2s

class App(object):
    def __init__(self, root):
        self.root = root
        self.state = AppState()
        self.state.root = root
        self.state.on_device_read = self._update_statusbar

        # variáveis da aba de sensores
        self.sensor_type_var = tk.StringVar()
        self.sensor_id_var = tk.StringVar()
        self.sensor_value_var = tk.StringVar()
        self.sensor_status_var = tk.StringVar()
        self.sensor_status_var.set("Aguardando detecção...")

        self.client_name_var = tk.StringVar()
        self.lot_var = tk.StringVar()

        self.sensor_tree = None
        self.sensor_counter = 0

        root.title("Giga Teste WE — SMETRO")
        try:
            root.geometry("980x700")
        except Exception:
            pass

        self.style = ttk.Style()
        try:
            if setup_style:
                setup_style(root)
            else:
                self.style.theme_use("clam")
        except Exception:
            pass
        self.style.configure(
            "Connection.On.TLabel",
            foreground="#1b6e3b",
            font=("TkDefaultFont", 10, "bold")
        )
        self.style.configure(
            "Connection.Off.TLabel",
            foreground="#9c2f2f",
            font=("TkDefaultFont", 10, "bold")
        )

        # Topbar
        self._build_topbar()

        # Notebook (inicialmente escondido)
        self.nb = ttk.Notebook(root)
        self.tabs_built = False

        # Tela de bloqueio
        self.lock = ttk.Frame(root)
        self._build_lock(self.lock)
        self.lock.pack(fill="both", expand=True, padx=10, pady=(0,10))

        # Status bar
        self.status_var = tk.StringVar()
        sb = ttk.Label(root, textvariable=self.status_var, anchor="w")
        sb.pack(fill="x", side="bottom")
        self._update_statusbar()

        # Portas
        self._refresh_ports(first=True)
        self.root.after(REFRESH_MS, self._auto_refresh_ports)

    # ---------- UI blocks ----------
    def _build_topbar(self):
        top = ttk.Frame(self.root)
        top.pack(fill="x", padx=10, pady=10)

        ttk.Label(top, text="Porta:").pack(side="left")
        self.port_var = tk.StringVar()
        self.port_cb = ttk.Combobox(top, textvariable=self.port_var, width=30, state="readonly", values=[])
        self.port_cb.pack(side="left", padx=(6,10))

        self.btn_refresh_ports = ttk.Button(
            top, text="Atualizar portas", command=self._refresh_ports
        )
        self.btn_refresh_ports.pack(side="left", padx=(0,6))
        self.btn_connect = ttk.Button(top, text="Conectar", command=self._connect)
        self.btn_connect.pack(side="left", padx=(0,6))
        self.btn_disconnect = ttk.Button(
            top, text="Desconectar", command=self._disconnect, state="disabled"
        )
        self.btn_disconnect.pack(side="left")

        self.connection_var = tk.StringVar(value="Desconectado")
        self.connection_badge = ttk.Label(
            top,
            textvariable=self.connection_var,
            style="Connection.Off.TLabel"
        )
        self.connection_badge.pack(side="right", padx=(12, 0))

    def _build_lock(self, frm):
        frm.grid_columnconfigure(0, weight=1)
        frm.grid_rowconfigure(0, weight=1)
        box = ttk.Frame(frm)
        box.grid(row=0, column=0, sticky="nsew")
        ttk.Label(box, text="Conecte a uma WE para continuar.", font=("TkDefaultFont", 12)).pack(pady=18)
        ttk.Label(box, text="Selecione a porta acima e clique em Conectar.\n"
                            "As abas só serão habilitadas após a conexão bem-sucedida.",
                  justify="center").pack()

    def _update_connection_controls(self):
        connected = bool(self.state.selected_port)
        has_port = bool((self.port_var.get() or "").strip())
        try:
            self.port_cb.configure(state="disabled" if connected else "readonly")
            self.btn_connect.configure(
                state="disabled" if connected or not has_port else "normal"
            )
            self.btn_disconnect.configure(state="normal" if connected else "disabled")
        except Exception:
            pass

    # ---------- Tabs lifecycle ----------
    def _add_tabs(self):
        if self.tabs_built:
            return
        if status_tab and hasattr(status_tab, "build_status_tab"):
            try:
                status_tab.build_status_tab(self.nb, self.state)
            except Exception as e:
                self._add_error_tab("Status", e)
        else:
            self._add_missing_tab("Status")

        if configure_tab and hasattr(configure_tab, "build_configure_tab"):
            try:
                configure_tab.build_configure_tab(self.nb, self.state)
            except Exception as e:
                self._add_error_tab("Configurar", e)
        else:
            self._add_missing_tab("Configurar")

        if firmware_tab and hasattr(firmware_tab, "build_firmware_tab"):
            try:
                firmware_tab.build_firmware_tab(self.nb, self.state)
            except Exception as e:
                self._add_error_tab("Firmware", e)
        else:
            self._add_missing_tab("Firmware")

        # Nova aba: Teste de Sensores (AT+DETECT?)
        self._add_sensor_tab()

        self.tabs_built = True

    def _teardown_tabs(self):
        if not self.tabs_built:
            return
        for tab_id in list(self.nb.tabs()):
            child = self.root.nametowidget(tab_id)
            self.nb.forget(child)
            try:
                child.destroy()
            except Exception:
                pass
        self.tabs_built = False

    def _add_missing_tab(self, name):
        frm = ttk.Frame(self.nb)
        ttk.Label(frm, text="Aba '{}' não encontrada.".format(name)).pack(padx=12, pady=12)
        self.nb.add(frm, text=name)

    def _add_error_tab(self, name, err):
        frm = ttk.Frame(self.nb)
        ttk.Label(frm, text="Falha ao inicializar '{}':\n{}".format(name, err)).pack(padx=12, pady=12)
        self.nb.add(frm, text=name)

    # ---------- Nova aba: Teste de Sensores ----------
    def _add_sensor_tab(self):
        frm = ttk.Frame(self.nb)
        self.nb.add(frm, text="Teste de Sensores")

        # Caixa de instrução
        instr = ttk.Label(
            frm,
            text=(
                "Conecte o sensor à jiga e clique em \"Detectar sensor\".\n"
                "O comando AT+DETECT? será enviado e os dados serão exibidos abaixo."
            ),
            justify="center"
        )
        instr.pack(padx=12, pady=10)

        # Frame principal dividido em cima (última detecção + dados de etiqueta) e baixo (histórico)
        top_frame = ttk.Frame(frm)
        top_frame.pack(fill="x", padx=12, pady=5)

        # Cartão de última detecção
        card = ttk.LabelFrame(top_frame, text="Última detecção")
        card.pack(side="left", fill="x", expand=True, padx=(0, 10))

        row = 0
        ttk.Label(card, text="Tipo do sensor:").grid(row=row, column=0, sticky="e", padx=5, pady=3)
        ttk.Label(card, textvariable=self.sensor_type_var, width=30).grid(row=row, column=1, sticky="w", padx=5, pady=3)
        row += 1

        ttk.Label(card, text="ID do sensor:").grid(row=row, column=0, sticky="e", padx=5, pady=3)
        ttk.Label(card, textvariable=self.sensor_id_var, width=30).grid(row=row, column=1, sticky="w", padx=5, pady=3)
        row += 1

        ttk.Label(card, text="Dado (s0):").grid(row=row, column=0, sticky="e", padx=5, pady=3)
        ttk.Label(card, textvariable=self.sensor_value_var, width=30).grid(row=row, column=1, sticky="w", padx=5, pady=3)
        row += 1

        ttk.Label(card, text="Status:").grid(row=row, column=0, sticky="e", padx=5, pady=3)
        ttk.Label(card, textvariable=self.sensor_status_var, width=30).grid(row=row, column=1, sticky="w", padx=5, pady=3)

        # Dados da etiqueta (Cliente, Lote, Grandeza)
        label_frame = ttk.LabelFrame(top_frame, text="Dados para etiqueta do sensor")
        label_frame.pack(side="left", fill="y", padx=(0, 10))

        r = 0
        ttk.Label(label_frame, text="Cliente:").grid(row=r, column=0, sticky="e", padx=5, pady=3)
        ttk.Entry(label_frame, textvariable=self.client_name_var, width=18).grid(row=r, column=1, sticky="w", padx=5, pady=3)
        r += 1

        ttk.Label(label_frame, text="Lote:").grid(row=r, column=0, sticky="e", padx=5, pady=3)
        ttk.Entry(label_frame, textvariable=self.lot_var, width=18).grid(row=r, column=1, sticky="w", padx=5, pady=3)
        r += 1


        # Botões
        btn_frame = ttk.Frame(top_frame)
        btn_frame.pack(side="right", fill="y")

        ttk.Button(
            btn_frame,
            text="Detectar sensor (AT+DETECT?)",
            command=self._on_detect_sensor
        ).pack(pady=(0, 5), ipadx=10)

        self.btn_print_sensor_label = ttk.Button(
            btn_frame,
            text="Imprimir etiqueta do sensor",
            command=self._on_print_sensor_label,
            state="disabled"
        )
        self.btn_print_sensor_label.pack(pady=5, ipadx=10)

        ttk.Button(
            btn_frame,
            text="Limpar histórico",
            command=self._clear_sensor_history
        ).pack(pady=5, ipadx=10)

        # Histórico em tabela
        hist_frame = ttk.LabelFrame(frm, text="Histórico de detecções")
        hist_frame.pack(fill="both", expand=True, padx=12, pady=10)

        cols = ("#", "tipo", "id", "s0", "timestamp")
        tree = ttk.Treeview(hist_frame, columns=cols, show="headings", height=10)
        tree.heading("#", text="#")
        tree.heading("tipo", text="Tipo")
        tree.heading("id", text="ID")
        tree.heading("s0", text="s0 (°C)")
        tree.heading("timestamp", text="Data/Hora")

        tree.column("#", width=40, anchor="center")
        tree.column("tipo", width=100, anchor="center")
        tree.column("id", width=200, anchor="center")
        tree.column("s0", width=80, anchor="center")
        tree.column("timestamp", width=150, anchor="center")

        tree.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(hist_frame, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")

        self.sensor_tree = tree
        self._update_sensor_print_state()

    def _clear_sensor_history(self):
        if self.sensor_tree is not None:
            for item in self.sensor_tree.get_children():
                self.sensor_tree.delete(item)
        self.sensor_counter = 0
        self.sensor_type_var.set("")
        self.sensor_id_var.set("")
        self.sensor_value_var.set("")
        self.sensor_status_var.set("Histórico limpo. Aguardando detecção...")
        self._update_sensor_print_state()

    def _reset_sensor_detection(self, message="Aguardando detecção..."):
        self.sensor_type_var.set("")
        self.sensor_id_var.set("")
        self.sensor_value_var.set("")
        self.sensor_status_var.set(message)
        self._update_sensor_print_state()

    def _update_sensor_print_state(self):
        sensor_id = (self.sensor_id_var.get() or "").strip()
        enabled = sensor_id not in ("", "-")
        try:
            self.btn_print_sensor_label.configure(
                state="normal" if enabled else "disabled"
            )
        except Exception:
            pass

    def _on_detect_sensor(self):
        if not self.state.selected_port:
            messagebox.showwarning("Aviso", "Nenhuma WE conectada. Conecte uma porta primeiro.")
            return

        port = self.state.selected_port
        generation = self.state.connection_generation
        self._reset_sensor_detection("Lendo sensor...")
        self.root.update_idletasks()
        self.state.show_busy("Detectando sensor...")

        def worker():
            try:
                result = detect_sensor(port)
            except Exception as e:
                self.state.root.after(
                    0, lambda err=e: self._on_detect_error(err, port, generation)
                )
                return

            self.state.root.after(
                0, lambda: self._on_detect_done(result, port, generation)
            )

        threading.Thread(target=worker, daemon=True).start()

    def _on_detect_error(self, err, port, generation):
        if not self.state.is_current_session(port, generation):
            return
        self.state.hide_busy()
        self._reset_sensor_detection("Erro na detecção.")
        messagebox.showerror("Erro", "Falha ao executar AT+DETECT?: {}".format(err))

    def _on_detect_done(self, result, port=None, generation=None):
        if port is not None and generation is not None:
            if not self.state.is_current_session(port, generation):
                return

        self.state.hide_busy()
        if not result:
            self._reset_sensor_detection("Não foi possível detectar o sensor.")
            return

        tipo = result.get("type") or "-"
        sid = result.get("id") or "-"
        value = result.get("value")
        if value is None:
            value_str = "N/D"
        else:
            try:
                value_str = "{:.2f}".format(float(value))
            except Exception:
                value_str = str(value)

        # Atualiza cartão
        self.sensor_type_var.set(tipo)
        self.sensor_id_var.set(sid)
        self.sensor_value_var.set(value_str)
        self.sensor_status_var.set("Detecção concluída com sucesso.")
        self._update_sensor_print_state()

        # Adiciona no histórico
        import datetime
        self.sensor_counter += 1
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        if self.sensor_tree is not None:
            self.sensor_tree.insert("", "end", values=(
                self.sensor_counter,
                tipo,
                sid,
                value_str,
                ts
            ))

    def _on_print_sensor_label(self):
        """
        Usa os dados da última detecção + cliente, lote e grandeza
        para chamar print_sensor_label do smetro_printer.py.
        """
        sensor_id = (self.sensor_id_var.get() or "").strip()
        sensor_type = (self.sensor_type_var.get() or "").strip()
        client_name = (self.client_name_var.get() or "").strip()
        lot = (self.lot_var.get() or "").strip()

        if sensor_id in ("", "-"):
            messagebox.showwarning(
                "Impressão",
                "Nenhum sensor detectado.\n\nDetecte um sensor antes de imprimir a etiqueta."
            )
            return

        if not lot:
            messagebox.showwarning(
                "Impressão",
                "Informe o LOTE para a etiqueta do sensor."
            )
            return

        self.state.show_busy("Enviando etiqueta do sensor...")
        try:
            self.btn_print_sensor_label.configure(state="disabled")
        except Exception:
            pass

        def worker():
            try:
                ok = print_sensor_label(
                    sensor_id=sensor_id,
                    sensor_type=sensor_type,
                    client_name=client_name,
                    lot=lot,
                )
                err = ""
            except Exception as e:
                ok = False
                err = str(e)

            def finish():
                self.state.hide_busy()
                self._update_sensor_print_state()
                if ok:
                    messagebox.showinfo(
                        "Impressão",
                        "Etiqueta do sensor enviada para impressão com sucesso."
                    )
                else:
                    messagebox.showerror(
                        "Impressão",
                        "Falha ao imprimir etiqueta do sensor:\n\n{}".format(
                            err or "A fila não confirmou o envio da etiqueta."
                        )
                    )

            self.state.root.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    # ---------- Portas ----------
    def _refresh_ports(self, first=False):
        try:
            ports = list_ports() or []
        except Exception:
            ports = []
        cur = self.port_var.get().strip()
        self.port_cb["values"] = ports
        if cur and cur in ports:
            self.port_var.set(cur)
        else:
            if self.state.selected_port and self.state.selected_port in ports:
                self.port_var.set(self.state.selected_port)
            else:
                self.port_var.set(ports[0] if ports else "")
        self.state.last_ports = ports[:]
        self._update_connection_controls()
        if not first:
            self._update_statusbar()

    def _auto_refresh_ports(self):
        try:
            ports = list_ports() or []
        except Exception:
            ports = []
        changed = (ports != self.state.last_ports)
        if changed:
            self.port_cb["values"] = ports
            self.state.last_ports = ports[:]
            if self.state.selected_port and self.state.selected_port not in ports:
                sel = self.state.selected_port
                self.state.end_session()
                self._reset_sensor_detection("Sensor desconectado. Aguardando nova detecção.")
                self._update_statusbar()
                self._hide_tabs_show_lock()
                messagebox.showwarning("Porta desconectada", "A porta '{}' foi desconectada.".format(sel))
                if self.port_var.get() not in ports:
                    self.port_var.set(ports[0] if ports else "")
                self._emit_connection_changed()
            self._update_connection_controls()
        try:
            self.root.after(REFRESH_MS, self._auto_refresh_ports)
        except Exception:
            pass

    def _connect(self):
        port = (self.port_var.get() or "").strip()
        if not port:
            messagebox.showwarning("Conectar", "Selecione uma porta.")
            return

        self.state.show_busy("Conectando...")
        self.root.update_idletasks()

        ok = False
        try:
            ok = test_connection(port)
        except Exception:
            ok = False

        if not ok:
            self.state.hide_busy()
            messagebox.showerror("Conectar",
                                 "Falha ao comunicar com a WE na porta '{}'.\n"
                                 "Verifique cabos/alimentação e tente novamente.".format(port))
            return

        # sucesso
        self.state.begin_session(port)
        self._reset_sensor_detection("Aguardando detecção...")
        self._update_statusbar()
        self._update_connection_controls()

        # tenta desabilitar logs
        try:
            write_at_command(port, "AT+LOG", "0")
        except Exception:
            pass

        self.state.hide_busy()
        self._show_tabs_hide_lock()
        self._emit_connection_changed()

    def _disconnect(self):
        if not self.state.selected_port:
            messagebox.showinfo("Desconectar", "Nenhuma porta conectada.")
            return
        sel = self.state.selected_port
        self.state.end_session()
        self._reset_sensor_detection("Sensor desconectado. Aguardando nova detecção.")
        self._update_statusbar()
        self._update_connection_controls()
        self._hide_tabs_show_lock()
        self._emit_connection_changed()
        messagebox.showinfo("Desconectar", "Desconectado de '{}'.".format(sel))

    # ---------- Alterna Notebook x Tela de bloqueio ----------
    def _show_tabs_hide_lock(self):
        self._add_tabs()
        try:
            self.lock.pack_forget()
        except Exception:
            pass
        try:
            self.nb.pack(fill="both", expand=True, padx=10, pady=(0,10))
        except Exception:
            pass

    def _hide_tabs_show_lock(self):
        self._teardown_tabs()
        try:
            self.nb.pack_forget()
        except Exception:
            pass
        try:
            self.lock.pack(fill="both", expand=True, padx=10, pady=(0,10))
        except Exception:
            pass

    # ---------- Eventos/UI ----------
    def _emit_connection_changed(self):
        try:
            self.root.event_generate("<<ConnectionChanged>>", when="tail")
        except Exception:
            pass

    def _update_statusbar(self):
        if self.state.selected_port:
            txt = "Porta: {}  |  Modelo: {}  |  ID: {}  |  FW: {}".format(
                self.state.selected_port,
                self.state.device_model or "-",
                self.state.device_id or "-",
                self.state.device_fw or "-"
            )
            self.connection_var.set("Conectado • {}".format(self.state.selected_port))
            self.connection_badge.configure(style="Connection.On.TLabel")
        else:
            txt = "Desconectado"
            self.connection_var.set("Desconectado")
            self.connection_badge.configure(style="Connection.Off.TLabel")
        self.status_var.set(txt)
        self._update_connection_controls()


def main():
    root = tk.Tk()

    # detecta se está rodando empacotado pelo PyInstaller
    if getattr(sys, 'frozen', False):
        base_path = sys._MEIPASS
    else:
        base_path = os.path.dirname(__file__)

    icon_path = os.path.join(base_path, "icon.png")
    try:
        root.iconphoto(False, tk.PhotoImage(file=icon_path))
    except Exception as e:
        print("Aviso: não foi possível carregar o ícone:", e)

    app = App(root)
    root.mainloop()

if __name__ == "__main__":
    main()
