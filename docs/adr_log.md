Architecture Decision Records (ADR) — Box3D
ADR-001: Strict Boundary Type Enforcement (Segurança de I/O)

    Contexto: O carregamento de perfis JSON dinâmicos permitia que falhas de tipagem (como valores null ou tipos inesperados) causassem interrupções críticas (AttributeError).

    Decisão: É obrigatória a validação explícita de tipos (isinstance) e checagem de nulidade antes de qualquer acesso a métodos de dicionário.

    Consequência: Estabilidade total na descoberta de perfis; um perfil malformado é ignorado sem derrubar o sistema.

ADR-002: OOM Hardening Policy (Lei de Ferro)

    Contexto: O processamento de imagens de alta resolução sem limites causava falhas de memória (Out Of Memory).

    Decisão: Implementação de um teto rígido de 8192px em duas camadas:

        Rejeição no carregamento do perfil (ProfileGeometry.__post_init__).

        Downscale preventivo (thumbnail) em todas as entradas de imagem antes do processamento pesado.

    Consequência: O sistema torna-se resiliente a "bombas de pixels" e assets abusivos.

ADR-003: Zero-Disk-Churn Architecture

    Contexto: A versão inicial utilizava ficheiros temporários em disco para comunicar entre o spine_builder e o compositor, gerando latência.

    Decisão: Eliminação de I/O intermediário. O pipeline agora transfere objectos PIL.Image.Image diretamente em memória.

    Consequência: Redução drástica da latência de escrita e proteção da vida útil de unidades SSD.