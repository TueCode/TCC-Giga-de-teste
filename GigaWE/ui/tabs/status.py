# -*- coding: utf-8 -*-
import os, sys, threading
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

import tkinter as tk
from tkinter import ttk, messagebox

from communication import (
    test_device,
    read_sensors,
    debug_read_ifconfig,
    parse_ifconfig,   # UX-4: usa a versão canônica de communication.py
)


# ======================================================
#            ABA STATUS (completa)
# ======================================================

def build_status_tab(nb, state):
    tab = ttk.Frame(nb)
    nb.add(tab, text="Status")

    for i in range(6):
        tab.grid_columnconfigure(i, weight=1)

    # ======================================================
    #    CABEÇALHO (Modelo / ID / FW)
    # ======================================================
    f = ttk.Labelframe(tab, text="Dispositivo")
    f.grid(row=0, column=0, columnspan=6, sticky="nsew", padx=12, pady=8)

    ttk.Label(f, text="Modelo:").grid(row=0, column=0, padx=6, pady=4, sticky="e")
    l_model = tk.StringVar()
    ttk.Label(f, textvariable=l_model).grid(row=0, column=1, sticky="w")

    ttk.Label(f, text="ID:").grid(row=0, column=2, padx=6, pady=4, sticky="e")
    l_id = tk.StringVar()
    ttk.Label(f, textvariable=l_id).grid(row=0, column=3, sticky="w")

    ttk.Label(f, text="FW:").grid(row=1, column=0, padx=6, pady=4, sticky="e")
    l_fw = tk.StringVar()
    ttk.Label(f, textvariable=l_fw).grid(row=1, column=1, sticky="w")

    # ======================================================
    #    HARDWARE (SENSORES)
    # ======================================================
    h = ttk.Labelframe(tab, text="Hardware")
    h.grid(row=1, column=0, columnspan=6, sticky="nsew", padx=12, pady=8)

    ttk.Label(h, text="Sensor 1:").grid(row=0, column=0, padx=6, pady=4, sticky="e")
    l_sensor1 = tk.StringVar()
    lbl_sensor1 = ttk.Label(h, textvariable=l_sensor1, foreground="#666")
    lbl_sensor1.grid(row=0, column=1, sticky="w")

    ttk.Label(h, text="Sensor 2:").grid(row=0, column=2, padx=6, pady=4, sticky="e")
    l_sensor2 = tk.StringVar()
    lbl_sensor2 = ttk.Label(h, textvariable=l_sensor2, foreground="#666")
    lbl_sensor2.grid(row=0, column=3, sticky="w")

    btn_read_sensors = ttk.Button(
        h, text="Ler sensores", command=lambda: ler_sensores()
    )
    btn_read_sensors.grid(row=0, column=4, padx=12, pady=4, sticky="w")

    # ======================================================
    #    TABELA (LEITURA AT PADRÃO)
    # ======================================================
    box = ttk.Labelframe(tab, text="Leitura completa (AT padrão)")
    box.grid(row=2, column=0, columnspan=6, sticky="nsew", padx=12, pady=8)
    tab.grid_rowconfigure(2, weight=1)

    cols = ("chave", "valor")
    tree = ttk.Treeview(box, columns=cols, show="headings", height=12)

    tree.heading("chave", text="CHAVE")
    tree.heading("valor", text="VALOR")

    tree.column("chave", anchor="w", width=240)
    tree.column("valor", anchor="w", width=520)

    tree.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)

    box.grid_columnconfigure(0, weight=1)
    box.grid_rowconfigure(0, weight=1)

    # ======================================================
    #               FUNÇÕES INTERNAS
    # ======================================================

    def _set_tree(k, v):
        """Atualiza ou insere item na tree."""
        for item in tree.get_children():
            key = tree.item(item, "values")[0]
            if key == k:
                tree.item(item, values=(k, v))
                return
        tree.insert("", "end", values=(k, v))

    active_operation = [None]

    def _set_operation(name=None):
        active_operation[0] = name
        state_name = "disabled" if name else "normal"
        for button in (btn_read_device, btn_read_sensors, btn_ifconfig):
            try:
                button.configure(state=state_name)
            except Exception:
                pass

    def _start_operation(name):
        if active_operation[0]:
            return False
        _set_operation(name)
        return True

    def _finish_operation(port, generation):
        if not state.is_current_session(port, generation):
            return False
        state.hide_busy()
        _set_operation()
        return True

    def preencher(d):
        """Preenche labels e tabela AT."""
        l_model.set(d.get("MODEL", ""))
        l_id.set(d.get("ID", ""))
        l_fw.set(d.get("VERSION", ""))

        l_sensor1.set(d.get("SENSOR1", ""))
        l_sensor2.set(d.get("SENSOR2", ""))

        tree.delete(*tree.get_children())

        for k, v in d.items():
            tree.insert("", "end", values=(k, v))

    # ======================================================
    #                LEITURA AT PADRÃO
    # ======================================================
    def ler():
        if not state.selected_port:
            messagebox.showwarning("Status", "Conecte a uma porta primeiro.")
            return
        if not _start_operation("device"):
            return

        port = state.selected_port
        generation = state.connection_generation

        def worker():
            try:
                d = test_device(port) or {}
            except Exception as e:
                print("[ERRO test_device]:", e)
                d = {}

            def finish():
                if not _finish_operation(port, generation):
                    return
                has_identity = any(
                    str(d.get(key) or "").strip()
                    for key in ("MODEL", "ID", "VERSION")
                )
                if not has_identity:
                    messagebox.showerror("Status", "Sem resposta válida da WE.")
                    return
                preencher(d)
                state.update_from_read(d, port=port, generation=generation)

            state.root.after(0, finish)

        state.show_busy("Lendo dispositivo...")
        threading.Thread(target=worker, daemon=True).start()

    # ======================================================
    #                     SENSORES
    # ======================================================
    def ler_sensores():
        if not state.selected_port:
            messagebox.showwarning("Sensores", "Conecte a uma porta primeiro.")
            return
        if not _start_operation("sensors"):
            return

        port = state.selected_port
        generation = state.connection_generation

        def worker():
            try:
                s0, s2 = read_sensors(port)
            except Exception as e:
                print("[ERRO read_sensors]:", e)
                s0, s2 = None, None

            # Função para tratar estado de cada sensor
            def process_sensor(val):
                if val is None:
                    return ("ERRO", "red")

                v = str(val).strip().lower()
                if v in ("", "none", "-", "0", "erro", "error", "na", "nan"):
                    return ("NÃO DETECTADO", "red")

                # Se o valor tem número válido:
                try:
                    float(v)
                    return (v, "black")
                except:
                    return ("FALHA DE LEITURA", "red")

            # Trata cada sensor
            s0_txt, s0_color = process_sensor(s0)
            s2_txt, s2_color = process_sensor(s2)

            # Atualiza interface (GUI)
            def update_ui():
                if not _finish_operation(port, generation):
                    return
                l_sensor1.set(s0_txt)
                l_sensor2.set(s2_txt)
                lbl_sensor1.configure(foreground=s0_color)
                lbl_sensor2.configure(foreground=s2_color)

                _set_tree("SENSOR1", s0_txt)
                _set_tree("SENSOR2", s2_txt)

                # Mensagens para o operador
                if s0_color == "red" or s2_color == "red":
                    messagebox.showwarning(
                        "Sensores",
                        "Um ou mais sensores não foram detectados.\n"
                        "Verifique conexões e tente novamente."
                    )

            state.root.after(0, update_ui)

        state.show_busy("Lendo sensores...")
        threading.Thread(target=worker, daemon=True).start()

    # ======================================================
    #                     IFCONFIG
    # ======================================================
    def ler_ifconfig():
        if not state.selected_port:
            messagebox.showwarning("IFCONFIG", "Conecte a uma porta primeiro.")
            return
        if not _start_operation("ifconfig"):
            return

        port = state.selected_port
        generation = state.connection_generation

        def worker():
            try:
                raw = debug_read_ifconfig(port)
            except Exception as e:
                print("[ERRO debug_read_ifconfig]:", e)
                raw = ""

            def show_window():
                if not _finish_operation(port, generation):
                    return
                if not raw:
                    messagebox.showerror("IFCONFIG", "Sem resposta da WE.")
                    return
                parsed = parse_ifconfig(raw)
                win = tk.Toplevel(state.root)
                win.title("IFCONFIG - Detalhes da Rede")
                win.geometry("520x380")
                win.minsize(420, 260)
                win.resizable(True, True)

                frame = ttk.Frame(win, padding=12)
                frame.pack(fill="both", expand=True)

                # Dados formatados
                for i, (k, v) in enumerate(parsed.items()):
                    ttk.Label(frame, text=f"{k}:", width=16, anchor="e").grid(row=i, column=0, pady=4)
                    ttk.Label(frame, text=v, foreground="blue").grid(row=i, column=1, sticky="w")

                # # Resposta crua para debug
                # ttk.Label(frame, text="\nResposta bruta:", foreground="gray")\
                #     .grid(row=len(parsed), column=0, columnspan=2)

                # txt = tk.Text(frame, height=6, width=65, font=("Courier", 9))
                # txt.grid(row=len(parsed)+1, column=0, columnspan=2)
                # txt.insert("1.0", raw)
                # txt.configure(state="disabled")

            state.root.after(0, show_window)

        state.show_busy("Lendo AT+IFCONFIG?")
        threading.Thread(target=worker, daemon=True).start()

    # ======================================================
    #                     BOTÕES
    # ======================================================
    btn_read_device = ttk.Button(tab, text="Ler do dispositivo", command=ler)
    btn_read_device.grid(row=3, column=0, padx=12, pady=10, sticky="w")

    btn_ifconfig = ttk.Button(tab, text="IFCONFIG", command=ler_ifconfig)
    btn_ifconfig.grid(row=3, column=1, padx=12, pady=10, sticky="w")

    # UX-1: auto-leitura ao conectar (500ms de delay para a porta estabilizar)
    def _on_connection_changed(event=None):
        if state.selected_port:
            tab.after(500, ler)

    tab.bind("<<ConnectionChanged>>", _on_connection_changed)

    return tab
