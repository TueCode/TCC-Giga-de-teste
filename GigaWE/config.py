# config.py — configurações centralizadas do Giga Teste WE

# Identificação do dispositivo
DEVICE_NAME = "SMETRO-WE"

# Comunicação serial
BAUD_RATE      = 115200
SER_TIMEOUT    = 2.0    # segundos
WRITE_TIMEOUT  = 2.0    # segundos

# Delays de comando AT (segundos)
PRE_DELAY_DEFAULT = 0.20
PRE_DELAY_SENSOR  = 1.00
INTER_CMD_DELAY   = 0.50
POST_DRAIN_TIME   = 0.12

# Retries em write_at_command
RETRIES = 1

# Auto-refresh de portas (ms)
REFRESH_MS = 2000
