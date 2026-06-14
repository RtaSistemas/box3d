# box3d — Arquitetura e Fluxos de Execução

## Visão Geral

box3d é estruturado em três camadas rígidas. Nenhuma camada pode importar de uma camada superior:

```
cli/ | gui/ | web/   ←  entrypoints (múltiplos, independentes)
         ↓
      core/           ←  domínio: tipos imutáveis + orquestração
         ↓
      engine/         ←  renderização pura (sem I/O, sem estado)
```

---

## 1. Mapa de Módulos

```mermaid
graph TD
    subgraph Entrypoints
        CLI["cli/main.py<br/>argparse + handlers"]
        GUI["gui/app.py<br/>CTk window"]
        WEB["web/server.py<br/>FastAPI + SSE"]
    end

    subgraph Core
        BOOT["cli/bootstrap.py<br/>path resolution"]
        REG["core/registry.py<br/>ProfileRegistry"]
        PIPE["core/pipeline.py<br/>RenderPipeline"]
        MOD["core/models.py<br/>Profile · RenderOptions<br/>RenderSummary · CoverResult"]
    end

    subgraph Engine ["Engine (pure functions, no I/O)"]
        COMP["engine/compositor.py<br/>compose_cover()"]
        SPIN["engine/spine_builder.py<br/>build_spine()"]
        PERSP["engine/perspective.py<br/>warp()"]
        BLEND["engine/blending.py<br/>screen · dst_in · composite"]
    end

    subgraph GUI_Tabs ["GUI Tabs"]
        CTRL["gui/control_tab.py<br/>ControlTab"]
        DSN["gui/designer_tab.py<br/>DesignerTab"]
        DSN_ENG["gui/designer_engine.py<br/>zoom · pan · hit-test"]
        FONTS["gui/fonts.py<br/>font registry"]
    end

    CLI --> BOOT
    CLI --> REG
    CLI --> PIPE
    GUI --> BOOT
    GUI --> CTRL
    GUI --> DSN
    WEB --> REG
    WEB --> PIPE
    CTRL --> PIPE
    CTRL --> REG
    CTRL --> FONTS
    DSN --> DSN_ENG
    PIPE --> COMP
    PIPE --> MOD
    REG --> MOD
    COMP --> SPIN
    COMP --> PERSP
    COMP --> BLEND
    SPIN --> PERSP
    SPIN --> BLEND
```

---

## 2. Fluxo CLI — Comando `render`

Sequência completa desde o terminal até o arquivo salvo em disco.

```mermaid
sequenceDiagram
    autonumber
    participant User as Terminal
    participant Main as cli/main.py
    participant Boot as cli/bootstrap.py
    participant Reg as core/registry.py
    participant Pipe as core/pipeline.py
    participant Comp as engine/compositor.py
    participant FS as Disco

    User->>Main: box3d render --profile mvs
    Main->>Boot: _bootstrap_data_dir()
    Boot->>FS: mkdir data/inputs/covers, data/output/...
    Main->>Reg: ProfileRegistry(profiles_dir).load()
    Reg->>FS: lê profile.json de cada subdir
    Reg-->>Main: Registry {name → Profile}
    Main->>Main: build RenderOptions (blur, darken, rgb, workers…)
    Main->>Pipe: RenderPipeline(profile, covers_dir, output_dir, options, logo_paths)
    Main->>Pipe: pipeline.run(on_progress=print_cb)

    Pipe->>Pipe: _validate() — template, covers_dir, logos
    Pipe->>FS: rglob covers_dir → list[Path]
    Pipe->>FS: _safe_open(template.png) → Image RGBA
    Pipe->>FS: _load_logo("top"), _load_logo("bottom")

    Note over Pipe: ThreadPoolExecutor(max_workers=N)<br/>cada cover em paralelo

    loop Para cada cover (paralelo)
        Pipe->>FS: _safe_open(cover.webp) → Image RGBA
        Pipe->>FS: _load_game_logo(stem) → Image RGBA | None
        Pipe->>Comp: compose_cover(cover, profile, options, logos, template)
        Comp-->>Pipe: result_img (RGBA)
        Pipe->>FS: result_img.save(output/cover.webp)
        Pipe->>Main: on_progress(done, total, CoverResult)
    end

    Pipe-->>Main: RenderSummary(total, succeeded, failed, elapsed…)
    Main->>User: imprime sumário no terminal
```

---

## 3. Pipeline Internos — Controle de Fluxo

```mermaid
flowchart TD
    A([run]) --> B{_validate OK?}
    B -- Não --> Z1([RenderSummary vazia])
    B -- Sim --> C[_collect: rglob covers_dir]
    C --> D{covers encontrados?}
    D -- Nenhum --> Z2([RenderSummary total=0])
    D -- Sim --> E[_safe_open template + logos<br/>pré-carregamento compartilhado]
    E --> F[ThreadPoolExecutor N workers]

    F --> G[as_completed loop]
    G --> H[future.result → CoverResult]
    H --> I[_stats update com Lock]
    I --> J[on_progress callback<br/>antes do breaker — BUG-04]
    J --> K{stop_event?}
    K -- Sim --> L[cancel pending futures]
    L --> Z3([RenderSummary com parcial])
    K -- Não --> M{Circuit Breaker?}
    M -- consecutive > 10<br/>ou total > 20% --> N[log.critical<br/>cancel pending]
    N --> Z4([RenderSummary breaker_tripped=True])
    M -- OK --> G

    subgraph _process_one [_process_one — em thread worker]
        P1{stop_event?} -->|Sim| R1([CoverResult skip])
        P1 -->|Não| P2{dry_run?}
        P2 -->|Sim| R2([CoverResult dry])
        P2 -->|Não| P3{skip_existing?}
        P3 -->|Sim| R3([CoverResult skip])
        P3 -->|Não| P4[_safe_open cover<br/>_load_game_logo stem]
        P4 --> P5[compose_cover]
        P5 --> P6[result_img.save]
        P6 --> R4([CoverResult ok])
        P4 -->|exception| R5([CoverResult error msg])
    end
```

---

## 4. Engine — Pipeline de Composição por Cover

`compose_cover()` é o único ponto de entrada no engine. Orquestra 5 etapas sequenciais, todas em memória (PIL Images RGBA).

```mermaid
flowchart LR
    IN["cover_img · profile · options\nlogos · template_img\n(todos PIL RGBA)"]

    subgraph STEP1 ["① Spine"]
        S1A["build_spine(cover, geom, layout, logos)\n→ spine_strip RGBA"]
        S1B["resize_for_fit(spine_strip, spine_w, spine_h)\n→ spine_src RGBA"]
        S1C["warp(spine_src, canvas, spine_quad)\n→ spine_warped RGBA"]
        S1D["alpha_composite(canvas, spine_warped)"]
        S1A --> S1B --> S1C --> S1D
    end

    subgraph STEP2 ["② Cover"]
        S2A["resize_for_fit(cover_img, cover_w, cover_h, fit_mode)\n→ cover_src RGBA"]
        S2B["warp(cover_src, canvas, cover_quad)\n→ cover_warped RGBA"]
        S2C["_sharpen_rgb(cover_warped)\nunsharp mask em RGB, preserva alpha"]
        S2D["linear_alpha_composite(canvas, cover_warped)\nPorter-Duff em linear light"]
        S2A --> S2B --> S2C --> S2D
    end

    subgraph STEP3 ["③ Template"]
        S3A["apply_color_matrix(template, rgb_matrix)\n→ colored_template RGBA"]
        S3B["alpha_weighted_screen(canvas, colored_template)\nscreen blend em linear light"]
        S3A --> S3B
    end

    subgraph STEP4 ["④ Silhueta"]
        S4A["build_silhouette_mask(spine, cover, template)\n→ union das alphas"]
        S4B["GaussianBlur(mask, radius=1.0)\nanti-aliasing de borda"]
        S4C["dst_in(canvas, mask)\nα_out = α_canvas × α_mask"]
        S4A --> S4B --> S4C
    end

    OUT["result_img RGBA\n(template_w × template_h)"]

    IN --> STEP1 --> STEP2 --> STEP3 --> STEP4 --> OUT
```

---

## 5. Spine Builder — Construção da Lombada

```mermaid
flowchart TD
    IN["cover_img · geom · layout · logos\nblur_radius · darken_alpha"]

    A["Calcular região de amostragem\nsource_frac × cover_w\n(left | right | center)"]
    B["cover.crop(x0,0,x1,ch)\n→ strip"]
    C["strip.resize(spine_w, spine_h, LANCZOS)\n→ scaled"]
    D["GaussianBlur(scaled, radius=blur_radius)\n→ blurred"]
    E["blurred.convert('RGBA')\n→ canvas"]
    F["overlay = Image.new('RGBA', (w,h), (0,0,0,darken_alpha))\nalpha_composite(canvas, overlay)"]
    G["_paste_logo(canvas, top_logo, slot_top)\n→ rotate · scale-down · opacity · center"]
    H["_paste_logo(canvas, game_logo, slot_game)"]
    I["_paste_logo(canvas, bottom_logo, slot_bottom)"]
    OUT["spine_strip RGBA\n(spine_w × spine_h)"]

    IN --> A --> B --> C --> D --> E --> F --> G --> H --> I --> OUT

    note1["Logos: nunca upscale\nscale = min(max_w/lw, max_h/lh, 1.0)\nopacity via numpy α channel × logo_alpha"]
    G -.-> note1
```

---

## 6. Perspective Warp — Dual Backend

```mermaid
flowchart TD
    IN["src: Image RGBA\ncanvas_w · canvas_h · dst_pts list[tuple]"]

    A["solve_coefficients(src_pts, dst_pts)\n→ _solve_cached() com @lru_cache(64)\n→ 8-tuple coeficientes homografia inversa"]

    A --> B{pyvips disponível?}

    subgraph VIPS ["pyvips path (~11ms hit / ~60ms miss)"]
        V1["_get_coord_array(w, h, coeffs)\nOrderedDict cache (max 16 entradas)\nfloat32 numpy (H,W,2): src_x, src_y por pixel"]
        V2["pyvips.Image.new_from_array(src_arr)\nzero-copy view do buffer PIL"]
        V3["pyvips.Image.new_from_array(idx_arr)\nzero-copy do array cacheado"]
        V4["src_vips.mapim(idx_vips,\ninterpolate=lbb | nohalo | bicubic | bilinear,\nextend=BACKGROUND, background=[0,0,0,0])"]
        V5["warped_vips.numpy() → PIL RGBA"]
        V1 --> V2 --> V3 --> V4 --> V5
    end

    subgraph PIL_PATH ["PIL fallback (~75ms)"]
        P1["src.transform((w,h), Image.PERSPECTIVE,\ncoeffs, Image.BICUBIC)\n→ binário 0/255 nas bordas"]
        P2["GaussianBlur(alpha, radius=feather)\nsuaviza borda binária"]
        P1 --> P2
    end

    B -- Sim --> VIPS
    B -- Não --> PIL_PATH

    VIPS --> OUT["warped RGBA\n(canvas_w × canvas_h)"]
    PIL_PATH --> OUT

    note["WARP_BACKEND_LABEL exposto\npara log no pipeline e GUI"]
    OUT -.-> note
```

---

## 7. Fluxo GUI — Desktop

### 7a. Inicialização

```mermaid
sequenceDiagram
    autonumber
    participant Entry as gui/app.py::main()
    participant Boot as cli/bootstrap.py
    participant Config as gui/config.py
    participant FontReg as gui/fonts.py
    participant App as App.__init__
    participant Ctrl as ControlTab.__init__
    participant Dsn as DesignerTab.__init__
    participant Reg as core/registry.py

    Entry->>Boot: _bootstrap_data_dir()
    Entry->>Config: load_config()
    Config-->>Entry: {font_scale, last_profile, covers_dir, …}
    Entry->>FontReg: init_scale(cfg["font_scale"])
    Entry->>App: App()
    App->>App: _build_header() — logo + tabs + A-/A+ + status
    App->>App: _build_content()
    App->>Ctrl: ControlTab(ctrl_frame)
    Ctrl->>Ctrl: _build_config_panel()
    Ctrl->>Ctrl: _build_progress_panel()
    Ctrl->>Ctrl: _build_preview_panel()
    Ctrl->>Reg: ProfileRegistry(_PROFILES).load()
    Reg-->>Ctrl: profiles_map
    Ctrl->>Config: load_config() → _restore_config()
    Ctrl->>Ctrl: _run_startup_diagnostic() → write pyvips log
    App->>Dsn: DesignerTab(dsgn_frame)
    Dsn->>Dsn: _build_left_panel() + _build_canvas() + _build_right_panel()
    App->>App: mainloop()
```

### 7b. Fluxo de Render no GUI

```mermaid
sequenceDiagram
    autonumber
    participant User as Usuário
    participant UI as ControlTab (main thread)
    participant Q as queue.Queue
    participant Worker as Thread Worker
    participant Pipe as RenderPipeline
    participant CTk as CTk.after scheduler

    User->>UI: clica START RENDER
    UI->>UI: _start_render() — valida campos
    UI->>UI: _cancel_event.clear()
    UI->>Worker: Thread(_run_pipeline).start()
    UI->>CTk: after(100ms, _poll_queue)

    Worker->>Pipe: RenderPipeline(…)
    Worker->>Pipe: pipeline.run(on_progress, stop_event)

    loop Para cada cover processada
        Pipe->>Worker: on_progress(done, total, CoverResult)
        Worker->>Q: queue.put({"type":"progress", …})
    end

    loop CTk.after(100ms) — main thread
        CTk->>UI: _poll_queue()
        UI->>Q: get_nowait() até Empty
        UI->>UI: _handle_event(event)
        Note over UI: atualiza progress bar<br/>log box · preview image
        UI->>CTk: after(100ms, _poll_queue)
    end

    Pipe-->>Worker: RenderSummary
    Worker->>Q: queue.put({"type":"done", summary…})
    Note over CTk,UI: próximo poll detecta "done"
    UI->>UI: _show_summary(data)
    UI->>UI: reset botão → START RENDER

    Note over User,UI: Cancelamento:<br/>User clica CANCEL<br/>→ _cancel_event.set()<br/>→ pipeline verifica stop_event<br/>→ cancela futures pendentes<br/>→ Worker envia {"type":"cancelled"}
```

### 7c. Escala de Fonte — Live Update

```mermaid
sequenceDiagram
    participant User as Usuário
    participant App as App (header)
    participant FontReg as gui/fonts.py
    participant Widgets as Todos os Widgets
    participant Config as gui/config.py

    User->>App: clica A+ ou A-
    App->>FontReg: step_up() | step_down() → new_scale
    App->>FontReg: set_scale(new_scale)
    FontReg->>FontReg: itera _registry [(font, base_size, weight, family)]
    FontReg->>Widgets: font.configure(size=int(base_size × new_scale))<br/>para cada CTkFont registrado
    Note over Widgets: CustomTkinter propaga automaticamente<br/>para todos os widgets que usam esse font object
    App->>App: _scale_label.configure(text="120%")
    App->>Config: load_config() → cfg["font_scale"] = 1.2 → save_config()
```

---

## 8. Fluxo Web Server — SSE Render

```mermaid
sequenceDiagram
    autonumber
    participant Browser as Browser / Cliente
    participant API as web/server.py (FastAPI)
    participant Q as _progress_queue
    participant Lock as _render_lock
    participant Exec as ThreadPoolExecutor(1)
    participant Pipe as RenderPipeline

    Browser->>API: GET /api/profiles
    API-->>Browser: [{name, template_w, template_h}, …]

    Browser->>API: GET /api/progress (SSE)
    API->>Browser: Connection: keep-alive<br/>text/event-stream

    Browser->>API: POST /api/render {profile, covers_dir, rgb, …}
    API->>Lock: acquire (409 se ocupado)
    API->>Q: limpar fila (drain)
    API->>Exec: run_in_executor(_run_pipeline)
    API-->>Browser: {"status": "started"}

    loop _run_pipeline em thread worker
        Exec->>Pipe: RenderPipeline(…).run(on_progress)
        loop Por cover processada
            Pipe->>Exec: on_progress callback
            Exec->>Q: queue.put({"done":N, "total":T, "stem":…, "status":…})
        end
        Pipe-->>Exec: RenderSummary
        Exec->>Q: queue.put({"done":-1, sumário completo})
        Exec->>Lock: release
    end

    loop SSE async generator (a cada 50ms)
        API->>Q: get_nowait()
        Q-->>API: event dict | Empty
        API->>Browser: data: {"done":N, "total":T, …}\n\n
    end

    Note over API,Browser: Quando done==-1:<br/>stream fecha automaticamente
```

---

## 9. Modelo de Dados — Tipos e Transformações

```mermaid
graph LR
    subgraph "Disco (leitura)"
        PJ["profile.json\n{name, template_size,\nspine_quad, cover_quad,\nspine_layout, …}"]
        IMG_T["template.png\nRGBA"]
        IMG_C["cover.webp/.png\nRGBA"]
        IMG_L["logo_top/bottom/game.*\nRGBA"]
    end

    subgraph "core/models.py (frozen dataclasses)"
        PROF["Profile\nname: str\nroot: Path\ngeometry: ProfileGeometry\nlayout: SpineLayout\ntemplate_path: Path"]
        GEOM["ProfileGeometry\ntemplate_w/h\nspine_w/h, cover_w/h\nspine_quad: Quad\ncover_quad: Quad\nspine_source_frac\nspine_source, cover_fit"]
        LAY["SpineLayout\ngame: LogoSlot\ntop: LogoSlot\nbottom: LogoSlot\nlogo_alpha: float"]
        OPT["RenderOptions\nblur_radius: int\ndarken_alpha: int\nrgb_matrix: str\ncover_fit: str\nspine_source: str\noutput_format: str\nworkers: int\nskip_existing: bool\ndry_run: bool"]
        RES["CoverResult\nstem: str\nstatus: ok|skip|error|dry\nelapsed: float\nerror: str|None"]
        SUM["RenderSummary\ntotal, succeeded\nskipped, failed, dry\nelapsed_time: float\nerrors: list[str]\nbreaker_tripped: bool"]
    end

    subgraph "engine/ (PIL Images RGBA)"
        SPINE["spine_strip\n(spine_w × spine_h)"]
        WARP_S["spine_warped\n(template_w × template_h)"]
        WARP_C["cover_warped\n(template_w × template_h)"]
        RESULT["result_img\n(template_w × template_h)"]
    end

    subgraph "Disco (escrita)"
        OUT["output/cover.webp\nWebP quality=92 | PNG"]
    end

    PJ --> PROF
    PROF --> GEOM
    PROF --> LAY
    IMG_T --> RESULT
    IMG_C --> SPINE
    IMG_C --> WARP_C
    IMG_L --> SPINE
    GEOM --> SPINE
    GEOM --> WARP_S
    GEOM --> WARP_C
    LAY --> SPINE
    OPT --> WARP_S
    OPT --> WARP_C
    SPINE --> WARP_S
    WARP_S --> RESULT
    WARP_C --> RESULT
    RESULT --> RES
    RES --> SUM
    RESULT --> OUT
```

---

## 10. Mapa de I/O e Threading

```mermaid
graph TD
    subgraph "Main Thread"
        MT1["Leitura de profile.json\n(registry.load)"]
        MT2["_safe_open(template)\npré-carregamento compartilhado"]
        MT3["_load_logo top/bottom\npré-carregamento compartilhado"]
    end

    subgraph "Worker Threads (N paralelos)"
        WT1["_safe_open(cover)\nleitura exclusiva por cover"]
        WT2["_load_game_logo(stem)\nleitura exclusiva por cover"]
        WT3["compose_cover\n100% em memória RAM"]
        WT4["result_img.save\nescrita exclusiva por output"]
    end

    subgraph "Proteções"
        LOCK["_lock: threading.Lock\nprotege _stats dict"]
        OOM["OOM Hardening\n_safe_open → thumbnail 8192px\nresize_for_fit → clamp 8192px"]
        CB["Circuit Breaker\n>10 consecutive errors\nou >20% total errors"]
        STOP["stop_event: threading.Event\ncancelamento cooperativo"]
    end

    subgraph "Regra de Ouro"
        RULE["engine/* = zero I/O\nzero global state\nthread-safe por construção"]
    end

    MT1 --> MT2 --> MT3
    MT3 --> WT1
    WT1 --> WT2 --> WT3 --> WT4
    WT3 -.-> LOCK
    WT1 -.-> OOM
    WT3 -.-> OOM
    WT4 -.-> CB
    STOP -.-> WT1
```

---

## 11. Bootstrap e Resolução de Paths

```mermaid
flowchart TD
    START([Startup])
    FR{sys.frozen?}

    START --> FR

    subgraph FROZEN ["PyInstaller --onefile / --onedir"]
        F1["_BUNDLE = sys._MEIPASS\n(assets read-only extraídos)"]
        F2["_DATA = Path(sys.executable).parent / 'data'\n(diretório persistente, próximo ao exe)"]
        F3["_PROFILES = exe.parent / 'profiles'\n(copiado de _MEIPASS na primeira execução)"]
    end

    subgraph DEV ["Dev / pip install"]
        D1["_BUNDLE = Path(__file__).parent.parent\n(raiz do projeto)"]
        D2["_DATA = _BUNDLE / 'data'"]
        D3["_PROFILES = _BUNDLE / 'profiles'"]
    end

    FR -- Sim --> FROZEN
    FR -- Não --> DEV

    FROZEN --> DIRS
    DEV --> DIRS

    subgraph DIRS ["_bootstrap_data_dir()"]
        DIR1["data/inputs/covers/"]
        DIR2["data/inputs/marquees/"]
        DIR3["data/output/converted/"]
        DIR4["data/output/logs/"]
    end

    DIRS --> INST["_bootstrap_instructions()\nescreve instructions.txt\nna primeira execução"]
    INST --> HOOK["hooks/hook-pyvips.py\nPyInstaller: coloca libvips na raiz do bundle\npara cffi.dlopen() encontrar em runtime"]
```

---

## Resumo — Princípios de Design

| Princípio | Onde | Como |
|---|---|---|
| **I/O exclusivo no pipeline** | `core/pipeline.py` | engine/* não tem acesso a disco |
| **Engine pure functions** | `engine/*` | sem estado global, thread-safe por construção |
| **OOM Hardening** | `_safe_open()` + `resize_for_fit()` | clamp 8192px em duas camadas independentes |
| **Circuit Breaker** | `pipeline.run()` | aborta batch com >10 erros consecutivos ou >20% |
| **Cancelamento cooperativo** | `threading.Event` | verificado em `_process_one` antes de cada cover |
| **on_progress antes do breaker** | `pipeline.run()` | o item que dispara o breaker é sempre reportado (BUG-04) |
| **Imutabilidade** | `core/models.py` | `@dataclass(frozen=True)` em todos os tipos de domínio |
| **Path traversal protection** | `core/registry.py` | `^[a-zA-Z0-9_-]+$` antes de qualquer acesso a disco |
| **Fonte live-scalable** | `gui/fonts.py` | `CTkFont.configure()` via registry centralizado |
| **Simplicity first** | todos os módulos | solução canônica preferida; complexidade só quando necessária |
