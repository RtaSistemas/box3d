Sprint Log — Ciclo v1.0.3
Sprint 1: Fundação & Segurança de Ingestão

    Foco: models.py e registry.py.

    Entregas:

        Validação strita de tipos no parser de JSON.

        Mitigação de Path Traversal no carregamento de nomes de perfis.

    Status: Concluído.

Sprint 2: Hardening do Motor Gráfico (Fase 1)

    Foco: blending.py e perspective.py.

    Entregas:

        Eliminação de alocações redundantes no NumPy (np.empty_like).

        Migração de transformações de cor para a API nativa em C do Pillow.

        Downscale preventivo no warp de perspetiva.

    Status: Concluído.

Sprint 3: Otimização de Orquestração (Zero-Disk)

    Foco: compositor.py e pipeline.py.

    Entregas:

        Remoção de ficheiros temporários (spine_tmp).

        Implementação de Pre-loaded Singleton para o template (carregado uma única vez por worker).

    Status: Concluído.

Sprint 4: Hardening de Assets Periféricos (Spine)

    Foco: spine_builder.py.

    Entregas:

        Proteção OOM no carregamento de logos.

        Remoção de dependência NumPy para transparência, usando métodos nativos do Pillow.

    Status: Concluído.