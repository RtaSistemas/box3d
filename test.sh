#!/usr/bin/env bash
# run.sh — executa box3d sem necessidade de instalação via pip
#
# Uso:
#   ./run.sh
#   ./run.sh --profile mvs --workers 8
#   ./run.sh --dry-run --verbose
#
# O PYTHONPATH aponta para src/ para que `import box3d` funcione
# independentemente de onde o script é chamado.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHONPATH="${SCRIPT_DIR}/src" exec python3 tests/run_visual_tests.py "$@"
