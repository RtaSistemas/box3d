#!/usr/bin/env bash
# test_cli_variations.sh
# Validação estrutural da camada CLI (v1.0.3)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOX3D_CMD="env PYTHONPATH=${SCRIPT_DIR} python3 ${SCRIPT_DIR}/cli/main.py"
COVERS_DIR="data/inputs/covers"

echo "============================================================"
echo " Iniciando Testes de CLI do Box3D (v1.0.3)"
echo "============================================================"

# Garantir que a pasta de input existe e contém um cover válido para os testes
mkdir -p "$COVERS_DIR"
cp "${SCRIPT_DIR}/tests/assets/cover.webp" "$COVERS_DIR/dummy_cover.webp"

echo "[1/4] Testando Limites Matemáticos e Seguranças (Fail-Fast)..."
# Deve falhar: Darken fora do limite
if $BOX3D_CMD render --profile mvs --input "$COVERS_DIR" --darken 300 2>/dev/null; then
  echo "FALHA: CLI aceitou --darken > 255"
  exit 1
else
  echo "✔ Proteção de --darken (300) funcionou."
fi

# Deve falhar: Blur negativo
if $BOX3D_CMD render --profile mvs --input "$COVERS_DIR" --blur-radius -10 2>/dev/null; then
  echo "FALHA: CLI aceitou --blur-radius negativo"
  exit 1
else
  echo "✔ Proteção de --blur-radius (-10) funcionou."
fi

# Deve falhar: Input dir inexistente
if $BOX3D_CMD render --profile mvs --input "dir_fake_999" 2>/dev/null; then
  echo "FALHA: CLI aceitou diretório de input inválido."
  exit 1
else
  echo "✔ Proteção de I/O Fail-Fast funcionou."
fi

echo "[2/4] Testando Comandos Base do CLI..."
$BOX3D_CMD profiles list
$BOX3D_CMD profiles validate
echo "✔ Comandos de 'profiles' responderam com sucesso."

echo "[3/4] Testando Variações de Argumentos de Render (Dry-Run)..."
# Simulação rápida de stress de parâmetros sem alocação gráfica pesada
VARS=(
  "--profile mvs --blur-radius 0 --darken 0"
  "--profile arcade --rgb 1.2,1.2,1.2"
  "--profile dvd --spine-source right --cover-fit crop"
  "--profile mvs --no-rotate --no-logos --output-format png"
  "--profile arcade --workers 8 --skip-existing"
)

for v in "${VARS[@]}"; do
  echo "  Executando: render $v --dry-run"
  $BOX3D_CMD render $v --input "$COVERS_DIR" --dry-run > /dev/null
done
echo "✔ Todas as variações sintáticas executadas sem falhas de parse."

echo "[4/4] Testando Conflitos de Matriz RGB..."
# Deve falhar: Formato RGB inválido
if $BOX3D_CMD render --profile mvs --input "$COVERS_DIR" --rgb "1.0,AB" 2>/dev/null; then
  echo "FALHA: CLI aceitou string RGB inválida."
  exit 1
else
  echo "✔ Proteção de matriz RGB funcionou."
fi

echo "============================================================"
echo " TODOS OS TESTES PASSARAM. O CLI ESTÁ BLINDADO."
echo "============================================================"
