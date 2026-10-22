# Frozen window9 demo timing contract. SKY130HD uses ns and pF.
# No board-level or manufacturing signoff is implied by this contract.
create_clock -name clk -period 100.0 [get_ports clk]
set_clock_uncertainty -setup 0.1 [get_clocks clk]
set_clock_uncertainty -hold 0.05 [get_clocks clk]
set data_inputs [get_ports {ui_in[*] uio_in[*] rst_n ena}]
set_input_delay -clock clk -max 20.0 $data_inputs
set_input_delay -clock clk -min 0.0 $data_inputs
set_input_transition 0.2 $data_inputs
set_output_delay -clock clk -max 20.0 [all_outputs]
set_output_delay -clock clk -min 0.0 [all_outputs]
set_load 0.05 [all_outputs]
# Synchronous reset and enable remain timed. No false-path exceptions.
