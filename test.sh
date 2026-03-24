#!/usr/bin/env bash
# test.sh — executa os testes visuais sem necessidade de instalação via pip
#
# Uso:
#   ./test.sh
#   ./test.sh --profile mvs --workers 8
#   ./test.sh --dry-run --verbose
#
# PYTHONPATH aponta para a raiz do projecto para que os módulos
# core/, engine/ e cli/ sejam importáveis directamente.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PYTHONPATH="${SCRIPT_DIR}" exec python3 tests/run_visual_tests.py "$@"
