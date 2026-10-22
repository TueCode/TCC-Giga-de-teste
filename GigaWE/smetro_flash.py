# smetro_flash.py  (Python 3.6) — versão enxuta
# -*- coding: utf-8 -*-
from __future__ import print_function
import os
import sys
import tarfile
import subprocess

DEFAULT_BAUD = 921600
OFFS_BOOT   = 0x1000
OFFS_PART   = 0x8000
OFFS_APP    = 0x10000

class SmetroFlash(object):
    """
    Uso típico:
        fl = SmetroFlash("/dev/ttyUSB0", "/caminho/firmware.smetro")
        err = fl.unpack()
        if not err: err = fl.erase()
        if not err: err = fl.flash()
    Todos os métodos retornam "" (ok) ou string com erro.
    """
    def __init__(self, port, package, baud=DEFAULT_BAUD):
        self.port = str(port)
        self.package = package                 # .tar/.smetro OU diretório
        self.baud = int(baud)
        _base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
        self.tmp_dir = os.path.join(_base, ".package")

        self.bootloader_bin = ""
        self.partitions_bin = ""
        self.firmware_bin   = ""

    # -------------------- público --------------------

    def unpack(self):
        """
        Aceita diretório com .bin ou arquivo .tar/.smetro.
        Se for .tar, extrai tudo "achatado" em ./.package
        """
        path = (self.package or "").strip()
        if not path:
            return "Caminho do pacote não informado."

        if os.path.isdir(path):
            return self._find_bins(path)

        if not os.path.isfile(path):
            return "Arquivo não encontrado: " + path

        # limpa tmp
        self._rm_tree(self.tmp_dir)
        try:
            os.makedirs(self.tmp_dir)
        except Exception:
            pass

        # extrai
        try:
            with tarfile.open(path, "r:*") as tf:
                for m in tf.getmembers():
                    m.name = os.path.basename(m.name)  # flatten
                    tf.extract(m, path=self.tmp_dir)
        except Exception as e:
            return "Erro ao descompactar '{}': {}".format(path, e)

        return self._find_bins(self.tmp_dir)

    def erase(self, on_line=None):
        """
        Apaga a flash inteira.
        Mantemos o chip NO bootloader após o erase para evitar reset manual.
        """
        args = [
            "--chip", "esp32",
            "--port", self.port,
            "--baud", str(self.baud),
            "--before", "default_reset",
            "--after",  "no_reset",
            "erase_flash",
        ]
        return self._run_esptool(args, on_line=on_line)

    def flash(self, on_line=None):
        """
        Grava bootloader, partitions e app nos offsets do legado.
        Força voltar ao bootloader antes de gravar; reseta ao final.
        """
        if not (self.bootloader_bin and self.partitions_bin and self.firmware_bin):
            return "Bins não preparados. Rode unpack() primeiro."

        args = [
            "--chip", "esp32",
            "--port", self.port,
            "--baud", str(self.baud),
            "--before", "default_reset",
            "--after",  "hard_reset",
            "write_flash", "-z",
            "--flash_mode", "dio",
            "--flash_freq", "40m",
            "--flash_size", "detect",
            hex(OFFS_BOOT), self.bootloader_bin,
            hex(OFFS_PART), self.partitions_bin,
            hex(OFFS_APP),  self.firmware_bin,
        ]
        return self._run_esptool(args, on_line=on_line)

    # compat do legado (não usada pelo app, mas útil em script)
    def erase_and_flash(self, on_line=None):
        err = self.erase(on_line=on_line)
        if err: return err
        return self.flash(on_line=on_line)

    # -------------------- internos --------------------

    def _find_bins(self, base_dir):
        boot = os.path.join(base_dir, "bootloader.bin")
        part = os.path.join(base_dir, "partitions.bin")
        app1 = os.path.join(base_dir, "smetro-we.bin")
        app2 = os.path.join(base_dir, "app.bin")
        app  = app1 if os.path.isfile(app1) else app2

        if not os.path.isfile(boot): return "bootloader.bin não encontrado em " + base_dir
        if not os.path.isfile(part): return "partitions.bin não encontrado em " + base_dir
        if not os.path.isfile(app):  return "smetro-we.bin/app.bin não encontrado em " + base_dir

        self.bootloader_bin = boot
        self.partitions_bin = part
        self.firmware_bin   = app
        return ""

    def _run_esptool(self, args, on_line=None):
        """
        Sempre usa o Python atual: `python -m esptool ...`
        on_line(txt): callback chamado para cada linha de saída (stdout+stderr),
                      útil para exibir progresso em tempo real.
        Retorna "" se returncode==0; senão, texto do erro.
        """
        import subprocess
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "esptool"] + args,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
            )
            output_lines = []
            for raw in iter(proc.stdout.readline, b""):
                line = raw.decode("utf-8", "ignore").rstrip()
                output_lines.append(line)
                if on_line:
                    try:
                        on_line(line)
                    except Exception:
                        pass
            proc.wait(timeout=240)
            if proc.returncode == 0:
                return ""
            return "\n".join(output_lines[-20:]) or "esptool retornou código {}".format(proc.returncode)
        except FileNotFoundError:
            return "esptool não está instalado neste ambiente Python."
        except Exception as e:
            return str(e)

    def _rm_tree(self, path):
        try:
            if not os.path.isdir(path):
                return
            for root, dirs, files in os.walk(path, topdown=False):
                for f in files:
                    try: os.remove(os.path.join(root, f))
                    except Exception: pass
                for d in dirs:
                    try: os.rmdir(os.path.join(root, d))
                    except Exception: pass
            try: os.rmdir(path)
            except Exception: pass
        except Exception:
            pass
