# 图像核心与 RTL 仿真

Linux、Python 3.12、Node.js 24、Docker；Icarus/cocotb 用于仿真，LibreLane/SKY130 用于物理实现。

## 运行整数参考

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install Pillow==11.3.0
python -m unittest verification.test_oracle
python examples/image_reference.py
```
`outputs/` 中生成 Sobel 边缘、Gaussian 平滑和锐化三种参考图像。三份可综合 RTL 位于 `designs/`；RTL 仿真与物理实现见 [EDA 上手](physical-design.md)。

## 组织新设计

`app/cli.py` 提供规格读取、创建任务、提交 RTL、功能验证、物理实现和签收等工具；`plugins/chipforge-tools/` 把这些操作注册到 AGH。完整环境步骤见 [EDA.md](physical-design.md)。

三份设计：

| 目录 | 功能 |
|---|---|
| `designs/sobel_fast` | Sobel 边缘提取 |
| `designs/sobel_compact` | 资源复用 Sobel |
| `designs/image_multi` | 边缘、Gaussian 平滑与锐化多模式 |

## 参考模型检查

```bash
python -m unittest verification.test_oracle
```
