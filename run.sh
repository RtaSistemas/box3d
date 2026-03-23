#!/usr/bin/env bash
# run.sh — executa box3d e inicializa estrutura de dados se necessário
#
# Uso:
#   ./run.sh --profile mvs
#
# O script verifica a existência da pasta data/ e, se ausente, cria a 
# estrutura conforme a imagem de referência e copia os ativos de teste.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="${SCRIPT_DIR}/data"
ASSETS_DIR="${SCRIPT_DIR}/tests/assets"

# 1. Verificação e criação da estrutura de pastas
if [ ! -d "$DATA_DIR" ]; then
    echo "  ! Pasta 'data' não encontrada. Inicializando estrutura..."
    
    # Criação dos subdiretórios conforme imagem de referência
    mkdir -p "${DATA_DIR}/inputs/covers"
    mkdir -p "${DATA_DIR}/inputs/marquees"
    mkdir -p "${DATA_DIR}/output/converted"
    mkdir -p "${DATA_DIR}/output/logs"

    echo "  ✔ Árvore de diretórios criada."

    # 2. Cópia e renomeio de arquivos de teste (Assets)
    # Copia cover.webp -> covers/std.webp
    if [ -f "${ASSETS_DIR}/cover.webp" ]; then
        cp "${ASSETS_DIR}/cover.webp" "${DATA_DIR}/inputs/covers/std.webp"
        echo "  ✔ Asset de capa 'std.webp' inicializado."
    fi

    # Copia marquee.webp -> marquees/std.webp
    if [ -f "${ASSETS_DIR}/marquee.webp" ]; then
        cp "${ASSETS_DIR}/marquee.webp" "${DATA_DIR}/inputs/marquees/std.webp"
        echo "  ✔ Asset de marquee 'std.webp' inicializado."
    fi
fi

# Mantém PYTHONPATH na raiz do projecto para que os módulos core/, engine/
# e cli/ sejam resolvidos sem instalação via pip.
PYTHONPATH="${SCRIPT_DIR}" exec python3 cli/main.py "$@"