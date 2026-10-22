# 从图像核心到版图

## 运行条件

Linux x86_64、Docker、Python 3.12；Icarus Verilog 12、cocotb 2.0.0；LibreLane 3.0.14、SKY130A `sky130_fd_sc_hd`。

## 安装与 AGH

```bash
bash scripts/prepare_toolchain.sh
source scripts/env.sh
export AGH_SOURCE_DIR=/opt/agnes-harness
export CHIPFORGE_TT_TEMPLATE_DIR=/opt/ttsky-template
export CHIPFORGE_TT_TOOLS_DIR=/opt/tt-support-tools
(cd "$AGH_SOURCE_DIR" && pnpm install --frozen-lockfile && pnpm --filter @agnes/cli build:local)
python scripts/connect_agh.py
docker build -f scripts/Dockerfile.sim -t chipforge-sim:20261003 .
```

`patches/` 保存项目的接口适配补丁，可在外部 AGH 工作区应用后构建。项目连接脚本仅生成本地依赖连接和 SDK 构建；`--check` 只核对路径。通过 AGH 配置模型账户，模型选择文件为 `model.selection.json`；插件为 `plugins/chipforge-tools/`。

## 核心 RTL 仿真

```bash
mkdir -p outputs/sobel-fast/rtl
cp designs/sobel_fast/project.v outputs/sobel-fast/rtl/project.v
cp designs/sobel_fast/spec.json outputs/sobel-fast/spec.json
docker run --rm -e PYTHONPATH=/workspace -v "$PWD:/workspace:ro" -v "$PWD/outputs/sobel-fast:/candidate" chipforge-sim:20261003 python /workspace/verification/run_sim.py
```

更换 `designs/` 下的目录即可验证另外两份设计。验证结果写入输出目录的 `verification/`。

## AGH 设计流程

1. 创建任务：

   ```bash
   echo '{"design_id":"sobel_fast","request":"实现图像边缘提取核心"}' | .venv/bin/python app/cli.py new_run
   ```

2. AGH 调用 `submit_rtl`、`validate` 生成与检查候选。
3. 配置 `pdk/sky130A`，通过 `harden` 提交 LibreLane 与 Tiny Tapeout 流程。
4. 通过验证和物理结果反馈继续修复，并生成设计交付。

时钟和 I/O 参数在 `constraints/image_chip.sdc`，三类规格在 `specs/`。新的候选与版图由工具写入 `runs/`，计数器从新项目状态开始。

## 外部依赖版本

| 依赖 | 使用的版本或提交 |
|---|---|
| AGH 适配补丁基线 | `e4e782fdde270a484cf5154f9338253acb2cfffd` |
| ttsky-template | `68c3fd3f3ec640e5edcb6a5f74f360ebc016bb2a` |
| tt-support-tools | `01d5d2814fa9dd61e9d211e0b235a4a592a9316a` |
| LibreLane | `3.0.14` |
| SKY130 PDK | `sky130A`，`sky130_fd_sc_hd` |

将 Tiny Tapeout 依赖分别安装在上面的外部路径。连接脚本在已忽略的 `upstream/` 下建立本地引用。PDK 放在 `pdk/sky130A` 或由 `PDK_ROOT` 指定。

## 检查本次生成的候选

```bash
python scripts/run_full_template_precheck.py --run-id YOUR_RUN_ID --candidate-id YOUR_CANDIDATE_ID
python scripts/signoff_auditor.py --run-id YOUR_RUN_ID --candidate-id YOUR_CANDIDATE_ID
```

检查器读取该任务新产生的仿真、网表、时序和物理结果，生成新的检查报告。
