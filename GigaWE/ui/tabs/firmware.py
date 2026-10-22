# ui/tabs/firmware.py — Firmware + Etiqueta (CUPS/EPL via smetro_printer)
# -*- coding: utf-8 -*-
from __future__ import print_function
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

try:
    from smetro_flash import SmetroFlash
    HAS_FLASH = True
except Exception:
    SmetroFlash = None
    HAS_FLASH = False

import smetro_printer  # impressão via CUPS (igual ao legado)

BASE_PADX = 12
BASE_PADY = 8


def build_firmware_tab(nb, state):
    tab = ttk.Frame(nb)
    nb.add(tab, text="Firmware / Etiqueta")
    for i in range(6):
        tab.grid_columnconfigure(i, weight=1)

    # ======== Atualização de Firmware ========
    frm_sel = ttk.Labelframe(tab, text="Atualização de Firmware")
    frm_sel.grid(row=0, column=0, columnspan=6, sticky="nsew", padx=BASE_PADX, pady=BASE_PADY)
    for i in range(6):
        frm_sel.grid_columnconfigure(i, weight=1)

    bundle_var = tk.StringVar()
    ttk.Label(frm_sel, text="Pacote (.smetro/.tar):").grid(row=0, column=0, sticky="e", padx=6, pady=6)
    ttk.Entry(frm_sel, textvariable=bundle_var).grid(row=0, column=1, columnspan=3, sticky="we", padx=6, pady=6)
    ttk.Button(frm_sel, text="Selecionar…", command=lambda: _pick_bundle(bundle_var)) \
        .grid(row=0, column=4, sticky="w", padx=6, pady=6)

    port_var = tk.StringVar(value=state.selected_port or "(desconectado)")
    ttk.Label(frm_sel, text="Porta:").grid(row=1, column=0, sticky="e", padx=6, pady=4)
    ttk.Label(frm_sel, textvariable=port_var).grid(row=1, column=1, sticky="w", padx=6, pady=4)

    btn_update = ttk.Button(tab, text="Atualizar dispositivo",
                            command=lambda: _do_update(state, bundle_var, btn_update))
    btn_update.grid(row=1, column=0, sticky="w", padx=BASE_PADX, pady=(0, BASE_PADY))

    # ======== Etiqueta ========
    lab = ttk.Labelframe(tab, text="Imprimir etiqueta")
    lab.grid(row=2, column=0, columnspan=6, sticky="nsew", padx=BASE_PADX, pady=(0, BASE_PADY))
    for i in range(6):
        lab.grid_columnconfigure(i, weight=1)

    model_var = tk.StringVar(value="")
    id_var = tk.StringVar(value="")
    hw_var = tk.StringVar(value="")
    lot_var = tk.StringVar(value="")

    ttk.Label(lab, text="MODEL:").grid(row=0, column=0, sticky="e", padx=6, pady=6)
    ttk.Entry(lab, textvariable=model_var, width=24).grid(row=0, column=1, sticky="w", padx=6, pady=6)

    ttk.Label(lab, text="ID:").grid(row=0, column=2, sticky="e", padx=6, pady=6)
    ttk.Entry(lab, textvariable=id_var, width=24).grid(row=0, column=3, sticky="w", padx=6, pady=6)

    ttk.Label(lab, text="HW Version:").grid(row=1, column=0, sticky="e", padx=6, pady=6)
    ttk.Entry(lab, textvariable=hw_var, width=24).grid(row=1, column=1, sticky="w", padx=6, pady=6)

    ttk.Label(lab, text="Lote:").grid(row=1, column=2, sticky="e", padx=6, pady=6)
    ttk.Entry(lab, textvariable=lot_var, width=24).grid(row=1, column=3, sticky="w", padx=6, pady=6)

    ttk.Button(lab, text="↻ Ler da aba Status",
               command=lambda: _fill_from_state(state, model_var, id_var, hw_var, lot_var)) \
        .grid(row=0, column=4, rowspan=2, sticky="w", padx=6, pady=6)

    # lista de impressoras do CUPS
    try:
        printers = smetro_printer.list_printers()
    except Exception:
        printers = []
    if not printers:
        printers = [smetro_printer.CUPS_QUEUE_WE]

    cups_var = tk.StringVar(value=printers[0])
    ttk.Label(lab, text="Fila CUPS:").grid(row=2, column=0, sticky="e", padx=6, pady=6)
    cb_cups = ttk.Combobox(lab, textvariable=cups_var, values=printers, state="readonly", width=28)
    cb_cups.grid(row=2, column=1, sticky="w", padx=6, pady=6)

    btn_print = ttk.Button(
        lab, text="Imprimir etiqueta",
        command=lambda: _do_print(model_var.get(), id_var.get(), hw_var.get(), lot_var.get(), cups_var.get(), state)
    )
    btn_print.grid(row=3, column=0, sticky="w", padx=6, pady=(6, 6))

    # ======== habilitação ========
    def _update_enabled(*_):
        try:
            # sempre deixa o botão de imprimir habilitado
            btn_print.configure(state="normal")
        except Exception:
            pass

        try:
            # botão de atualizar firmware continua dependendo da conexão
            btn_update.configure(state=("normal" if state.selected_port else "disabled"))
        except Exception:
            pass

        # atualiza o campo de porta
        port_var.set(state.selected_port or "(desconectado)")

    tab.bind("<<ConnectionChanged>>", lambda e: _update_enabled())
    nb.bind("<<NotebookTabChanged>>", lambda e: _update_enabled())
    _update_enabled()
    return tab


# ---------------- helpers ----------------
def _pick_bundle(var):
    p = filedialog.askopenfilename(
        title="Selecione o pacote (.smetro/.tar) OU cancele para escolher uma pasta",
        filetypes=[("Pacote SMETRO", "*.smetro *.tar"), ("Todos", "*.*")]
    )
    if p:
        var.set(p)
        return
    d = filedialog.askdirectory(title="Selecione a pasta de firmware")
    if d:
        var.set(d)


def _fill_from_state(state, model_var, id_var, hw_var=None, lot_var=None):
    try:
        if state and getattr(state, "device_model", None):
            model_var.set(state.device_model)
        if state and getattr(state, "device_id", None):
            id_var.set(state.device_id)
        if hw_var is not None and getattr(state, "device_hw", None):
            hw_var.set(state.device_hw)
        if lot_var is not None and getattr(state, "device_lot", None):
            lot_var.set(state.device_lot)
    except Exception:
        pass


# ---------------- ações ----------------
def _do_update(state, bundle_var, btn):
    if not HAS_FLASH:
        messagebox.showerror("Firmware", "smetro_flash.py indisponível.")
        return
    if not state.selected_port:
        messagebox.showwarning("Firmware", "Conecte a uma porta primeiro.")
        return

    path = (bundle_var.get() or "").strip()
    if not path:
        messagebox.showwarning("Firmware", "Selecione o pacote/pasta primeiro.")
        return

    # A gravação deve continuar apontando para a porta que o operador
    # confirmou. Uma troca de WE durante o processo não pode redirecionar a
    # chamada nem atualizar uma aba que já foi fechada.
    port = state.selected_port
    generation = state.connection_generation

    ok = messagebox.askokcancel(
        "Modo de atualização",
        "Para atualizar a WE:\n\n"
        "1) Coloque o JUMPER no IO0 (BOOT)\n"
        "2) REINICIE a placa\n\n"
        "Quando a WE estiver em modo bootloader, clique em OK.",
        icon="info"
    )
    if not ok:
        return

    # ── Janela de log ao vivo (UX-2) ──
    log_win = tk.Toplevel(state.root)
    log_win.title("Progresso do Firmware")
    log_win.geometry("660x360")
    log_win.resizable(True, True)
    log_win.protocol("WM_DELETE_WINDOW", lambda: None)  # não fechar durante flash

    frm = ttk.Frame(log_win, padding=8)
    frm.pack(fill="both", expand=True)

    ttk.Label(frm, text="Gravando firmware — aguarde…").pack(anchor="w")

    pb = ttk.Progressbar(frm, mode="indeterminate", length=640)
    pb.pack(fill="x", pady=(4, 6))
    pb.start(12)

    txt = tk.Text(frm, height=14, font=("Courier", 9), state="disabled", wrap="none")
    txt.pack(fill="both", expand=True)

    sb_y = ttk.Scrollbar(frm, orient="vertical", command=txt.yview)
    txt.configure(yscrollcommand=sb_y.set)
    sb_y.pack(side="right", fill="y")

    btn_close = ttk.Button(frm, text="Fechar", state="disabled",
                            command=log_win.destroy)
    btn_close.pack(anchor="e", pady=(6, 0))

    def append_log(line):
        """Chamado em thread worker — agenda atualização na UI via after()."""
        def _ui():
            if not state.is_current_session(port, generation):
                return
            try:
                txt.configure(state="normal")
                txt.insert("end", line + "\n")
                txt.see("end")
                txt.configure(state="disabled")
            except Exception:
                pass
        state.root.after(0, _ui)

    def worker():
        try:
            fl = SmetroFlash(port, path)
            err = fl.unpack()
            if not err:
                append_log("=== ERASE ===")
                err = fl.erase(on_line=append_log)
            if not err:
                append_log("=== FLASH ===")
                err = fl.flash(on_line=append_log)
        except Exception as e:
            err = str(e)

        def finish():
            if not state.is_current_session(port, generation):
                try:
                    pb.stop()
                    log_win.destroy()
                except Exception:
                    pass
                return
            try:
                pb.stop()
                btn_close.configure(state="normal")
                log_win.protocol("WM_DELETE_WINDOW", log_win.destroy)
            except Exception:
                pass
            state.hide_busy()
            try:
                btn.configure(state="normal")
            except Exception:
                pass
            if err:
                append_log("\n>>> ERRO: " + err)
                messagebox.showerror("Atualizar", "Falha na atualização:\n{}".format(err))
            else:
                append_log("\n>>> Firmware gravado com sucesso!")
                messagebox.showinfo(
                    "Atualização concluída",
                    "Firmware gravado com sucesso!\nRemova o jumper do IO0 e reinicie a WE."
                )

        state.root.after(0, finish)

    try:
        btn.configure(state="disabled")
    except Exception:
        pass
    state.show_busy("Gravando firmware...")
    threading.Thread(target=worker, daemon=True).start()


def _do_print(model, devid, hw_version, lot, cups_queue, state):
    model = (model or "").strip()
    devid = (devid or "").strip()
    if not model or not devid:
        messagebox.showwarning("Etiqueta", "Preencha MODEL e ID (ou use '↻ Ler da aba Status').")
        return

    def end_ok(msg):
        state.hide_busy()
        messagebox.showinfo("Etiqueta", msg)

    def end_err(msg):
        state.hide_busy()
        messagebox.showerror("Etiqueta", msg)

    state.show_busy("Enviando etiqueta...")

    def worker():
        try:
            smetro_printer.print_label(
                model=model,
                device_id=devid,
                hw_version=hw_version,
                lot=lot,
                printer_name=cups_queue
            )
            state.root.after(0, lambda: end_ok("Etiqueta enviada para '{}'.".format(cups_queue)))
        except Exception as e:
            state.root.after(0, lambda err=e: end_err("Falha ao imprimir:\n{}".format(err)))

    threading.Thread(target=worker, daemon=True).start()
