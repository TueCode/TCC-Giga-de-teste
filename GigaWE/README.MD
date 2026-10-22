# Giga Teste — SMETRO WE

Aplicativo de produção para conectar, consultar, configurar, registrar e atualizar dispositivos SMETRO WE. A execução começa em `main.py`, que abre `app.py`.

## Estrutura ativa

- `app.py`: janela principal, ciclo de conexão e aba de teste de sensores.
- `communication.py`: comunicação serial e comandos AT já usados pela WE.
- `ui/tabs/status.py`: leitura do dispositivo, sensores e IFCONFIG.
- `ui/tabs/configure.py`: configuração manual, arquivo legado e cadastro na Manager.
- `ui/tabs/firmware.py` e `smetro_flash.py`: gravação de firmware.
- `smetro_printer.py`: impressão das etiquetas existentes.
- `config_we.ini` e `config_we_wifi.ini`: exemplos de configuração legada.

## Requisitos

- Python 3.6 ou superior com Tkinter.
- Dependências Python listadas em `requirements.txt`. Para instalá-las, execute `pip install -r requirements.txt`.
- CUPS, `lp` e os pacotes já usados pela impressão para etiquetas.
- `esptool` é instalado pelas dependências do projeto e é usado na atualização de firmware.

## Uso

1. Execute `python3 main.py`.
2. Selecione a porta da WE e conecte.
3. Na aba **Status**, leia a WE antes de registrá-la na Manager.
4. Em **Configurar**, aplique os valores da tela ou carregue o arquivo legado.
5. Use **Firmware** quando for necessário gravar um pacote `.smetro`.

O aplicativo preserva a comunicação AT, os formatos de configuração, o cadastro legado na Manager e os layouts de etiqueta existentes.
