# Q Prepare / Edit / Freeze / Render

This workflow separates science from presentation:

```text
full standard 3-D data -> full derived Q surface -> preview geometry + view.json
                                                       | desktop edits only
                                                       v
                                              final.yml -> cluster render
```

## 1. Prepare on the cluster

For a volume input, use the ordinary Q configuration. `prepare` invokes the
same cached extractor as `pypost q extract`; a different Q iso value changes
the derived-data fingerprint, whereas a different camera does not.

```bash
pypost prepare q.yml --time 60.5 --out preview
```

For a ready-made Q surface, try the bundled example:

```bash
cd sciplot/demos/q_demo
pypost prepare q_surface.yml --out preview
```

The result has `scene.yml`, `preview.vtp`, `view.json`, and `manifest.json`.
`initial.png` is intentionally optional: a headless node can prepare geometry
without DISPLAY, EGL, or OSMesa. The manifest records protocol version, time,
the full derived source/signature, preview decimation, and presentation files.

## 2. Edit on a workstation

Copy only `preview/` to a desktop. It is safe to move because `preview.vtp`
and `view.json` are local. Run:

```bash
pypost edit preview/scene.yml
```

Use the native VTK mouse controls for rotation, pan, and zoom. Press `P` to
save camera and visual state to `view.json`; `M`, `B`, `+`/`-`, and `S` select
a colour map, toggle background, adjust opacity, and set scalar-bar state.
Text, labels, font size, image size, and precise colour limits remain clear
YAML settings in `scene.yml`. The editor never changes Q thresholds, velocity
interpolation, or mesh data. A server without graphical DISPLAY reports a
clear error; it can still run Prepare and Render.

## 3. Freeze and render back on the cluster

Return `view.json` (or the package), make sure `data_root` maps to the folder
containing the full Q surface, then freeze:

```bash
pypost freeze preview/scene.yml --out final.yml
pypost plot final.yml
pypost batch final.yml --resume
```

Freeze is file-only: it merges YAML defaults and view JSON, validates the full
source, rebases `data_root` relative to `final.yml`, and writes camera values
directly into editable YAML. It does not extract or render. It refuses a final
configuration whose source is `preview.vtp`.

`pypost plot final.yml` and `pypost batch final.yml --resume` use the existing
Q renderer and full source. Rendering requires a usable off-screen VTK backend
(DISPLAY, EGL, or OSMesa); otherwise it fails clearly rather than claiming an
image was produced.

---

# Q 的 Prepare / Edit / Freeze / Render（中文）

此流程将物理数据与显示参数分离：

```text
完整标准三维数据 -> 全精度派生 Q 等值面 -> 预览几何 + view.json
                                            | 仅桌面编辑显示状态
                                            v
                                   final.yml -> 集群最终渲染
```

## 1. 在集群 Prepare

对体数据使用普通 Q YAML：

```bash
pypost prepare q.yml --time 60.5 --out preview
```

它复用 `pypost q extract` 的缓存。修改 Q 等值会使派生表面缓存失效；修改相机不会。
`preview/` 至少含有 `scene.yml`、`preview.vtp`、`view.json`、`manifest.json`。
没有 DISPLAY/EGL/OSMesa 时仍会成功生成几何；`initial.png` 可缺失。

## 2. 在工作站 Edit

将 `preview/` 复制到桌面机器：

```bash
pypost edit preview/scene.yml
```

用 VTK 原生鼠标旋转、平移和缩放，按 `P` 保存 `view.json`。`M`、`B`、`+`/`-`、`S`
可调整色图、背景、透明度和色标状态。文字、字体、画面尺寸和精确色标范围可直接改
`scene.yml`。编辑器不会修改 Q 阈值、插值方式或任何物理数据。

## 3. Freeze 并回集群 Render

把 `view.json`（或整个目录）传回集群，并确保 `data_root` 指向全精度表面目录：

```bash
pypost freeze preview/scene.yml --out final.yml
pypost plot final.yml
pypost batch final.yml --resume
```

Freeze 只合并配置，不重新计算也不渲染；它拒绝使用 `preview.vtp` 作为最终源。最终
渲染使用完整表面，缺少 VTK 离屏后端时会明确报错。
