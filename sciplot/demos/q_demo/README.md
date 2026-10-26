# Portable Q workflow / 可移植 Q 工作流

`Q_sample.vtp` is a small supplied **derived Q surface** with the `speed`
colour array.  It is suitable for learning the portable presentation workflow;
it is not presented as a full CFD volume.

```bash
# Cluster or headless machine: no DISPLAY is needed.
pypost prepare q_surface.yml --time 60.5 --out preview

# Copy `preview/` to a workstation.  On the workstation:
pypost edit preview/scene.yml

# The editor uses native mouse rotate/pan/zoom. Press P to save view.json.
# Return view.json (or the whole preview directory) to the cluster.
pypost freeze preview/scene.yml --out final.yml
pypost plot final.yml
pypost batch final.yml --resume
```

`preview/preview.vtp` is intentionally simplified display geometry.  The
frozen `final.yml` points to the original full-resolution `Q_sample.vtp`
through `data_root`, never at `preview.vtp`.  If the preview directory is
moved, it can still be opened and its `view.json` edited.  Before Freeze on a
different machine, update the relative `data_root` in `scene.yml` to the
cluster location holding the full surface (or use an environment variable such
as `${PYPOST_DATA_ROOT}` there).

For a true volume-to-Q calculation, set `input.path` (or `input.time_index`),
`processing.velocity_field`, and `processing.iso` in a Q YAML. `prepare` will
reuse the normal Q extraction cache, write the full derived surface, then make
the independent preview geometry.

---

`Q_sample.vtp` 是包含 `speed` 着色数组的小型**派生 Q 等值面**，用于演示可移植的
显示工作流；它不是完整的 CFD 体数据。

```bash
# 集群或无显示服务器：不需要 DISPLAY。
pypost prepare q_surface.yml --time 60.5 --out preview

# 将 preview/ 拷贝至桌面工作站，再执行：
pypost edit preview/scene.yml

# 使用鼠标旋转/平移/缩放；按 P 保存 view.json。
# 将 view.json（或整个 preview 目录）传回集群：
pypost freeze preview/scene.yml --out final.yml
pypost plot final.yml
pypost batch final.yml --resume
```

`preview/preview.vtp` 只用于桌面显示。冻结后的 `final.yml` 通过
`data_root` 指向原始全精度 `Q_sample.vtp`，绝不会把 `preview.vtp` 当作最终
科学数据。移动 preview 后仍可编辑 `view.json`；若在另一台机器上 Freeze，请将
`scene.yml` 的相对 `data_root` 改为集群全精度表面位置（也可用
`${PYPOST_DATA_ROOT}` 等环境变量）。

若要从真实体数据计算 Q，在 YAML 设置 `input.path`（或 `input.time_index`）、
`processing.velocity_field` 和 `processing.iso`。`prepare` 会复用既有 Q 缓存，
先写全精度派生等值面，再生成独立预览几何。
