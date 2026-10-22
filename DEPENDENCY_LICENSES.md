# Design-flow dependencies

ChipForge implements the design executor, RTL examples, arithmetic references, verification, professional-tool integration and native AGH plugin. [Project license](LICENSE).

AGH is installed separately. The adaptation patches in `patches/` apply to the external AGH workspace; upstream Apache-2.0 terms continue to apply to modified upstream files.

Icarus Verilog, cocotb, LibreLane, Tiny Tapeout tools and the SKY130 PDK supply the simulation and physical-design environment. They are installed as external dependencies with their respective upstream licenses. Pillow supplies image input and reference-output handling.

Version pins and external dependency paths are documented in [the implementation guide](docs/physical-design.md).
