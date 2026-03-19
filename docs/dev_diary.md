Diário de Desenvolvimento — A Evolução do Box3D

O projeto iniciou-se como um gerador funcional, mas vulnerável a picos de recursos. Ao longo desta Release Candidate (RC), a postura arquitetural mudou de "apenas funcional" para "resiliente por design".

    A Descoberta do Gargalo: Identificámos que o maior custo não era a matemática da perspetiva, mas sim a gestão de memória do NumPy e o I/O de ficheiros temporários.

    A Lei de Ferro: A introdução do limite de 8192px foi polémica, mas necessária para garantir que o Box3D possa rodar em ambientes com recursos limitados (como handhelds de emulação) sem causar pânico no kernel.

    O Minimalismo: Ao final do ciclo, conseguimos reduzir as dependências externas ao estrito necessário: Pillow para manipulação e NumPy para álgebra linear.

4. Estrutura de Diretórios Atualizada (v1.0.3)
Plaintext

box3d/
├── core/
│   ├── models.py       ← Imutabilidade e validação OOM
│   ├── registry.py     ← Descoberta segura de plugins
│   └── pipeline.py     ← Orquestrador Zero-Disk-Churn
├── engine/
│   ├── perspective.py  ← Warp com downscale preventivo
│   ├── blending.py     ← Operações matemáticas NumPy otimizadas
│   ├── spine_builder.py← Construção de lombada nativa Pillow
│   └── compositor.py   ← Coordenação de memória RAM-to-RAM
├── docs/
│   ├── adr_log.md      ← Histórico de decisões técnicas
│   ├── sprint_log.md   ← Rastreabilidade de entregas
│   └── dev_diary.md    ← Narrativa de implementação
└── cli/
    └── main.py         ← Interface robusta de comando