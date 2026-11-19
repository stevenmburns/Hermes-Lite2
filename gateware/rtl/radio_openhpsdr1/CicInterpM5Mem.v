// CicInterpM5 with its comb state in one block RAM.
//
// Same ports, parameters and output, bit for bit, as CicInterpM5.v. The five
// integrators per channel still run on every enabled clock in registers. The
// combs run once every RRRR enabled clocks, so their state moves into a
// 64 x LO RAM (one M9K) and one LO-bit subtractor computes them serially.
//
// CicInterpM5's comb is pipelined: after comb event k,
//   x0(k) = input sampled at event k
//   xs(k) = x(s-1)(k-1) - x(s-1)(k-2)      s = 1..5
// and x5(k) feeds the first integrator on the next enabled clock. Every xs(k)
// for s >= 1 depends only on values from earlier events, so this version
// computes them in the gap after event k-1 and keeps x5(k) ready in x5n.
//
// RAM address {channel, stage[2:0], bank, half}: xs(k) is stored in bank k % 2,
// and each CBITS-wide value is split into a low half of LO bits and a high half
// of HI bits. After each event the sequencer
//   steps 0..3    writes the new x0 (I low, I high, Q low, Q high)
//   steps 4..43   issues 40 reads, 4 per (stage, channel) for stages 4 down to 0:
//                 A low = xs(k), B low = xs(k-1), A high, B high
//   steps 6..45   gets each read back two steps later and writes A - B
//                 (low half first, keeping the borrow) to x(s+1) in the other
//                 bank, or to x5n for stage 4
// Stages run high to low, so each write replaces a value its own stage has
// already read. The sequence ends at step 45, so RRRR must be at least 47
// (production uses 160 to 208).

module CicInterpM5Mem(
    input clock,
    input clock_en,             // enable an output sample
    output reg req,             // request the next input sample
    input signed [IBITS-1:0] x_real,    // input samples
    input signed [IBITS-1:0] x_imag,
    output signed [OBITS-1:0] y_real,   // output samples
    output signed [OBITS-1:0] y_imag
    );

    parameter RRRR = 320;       // interpolation; limited by size of counter
    parameter IBITS = 20;       // input bits
    parameter OBITS = 16;       // output bits
    parameter GBITS = 34;       // growth bits: growth is R**M / R
    localparam CBITS = IBITS + GBITS;   // calculation bits
    localparam LO = (CBITS + 1) / 2;    // low half, also the RAM width
    localparam HI = CBITS - LO;         // high half
    localparam LAST_STEP = 45;

    reg [8:0] counter = 9'd0;
    wire event_now = (counter == RRRR - 1);

    // ------------------------------------------------------------ integrators
    reg signed [CBITS-1:0] y1 = 0, y2 = 0, y3 = 0, y4 = 0, y5 = 0;
    reg signed [CBITS-1:0] s1 = 0, s2 = 0, s3 = 0, s4 = 0, s5 = 0;
    reg [LO-1:0] x5n_lo [0:1];
    reg [HI-1:0] x5n_hi [0:1];
    reg fire = 1'b0;    // the enabled clock after an event, when x5 is nonzero

    initial begin
        req = 1'b0;
        x5n_lo[0] = 0; x5n_lo[1] = 0;
        x5n_hi[0] = 0; x5n_hi[1] = 0;
    end

    wire signed [CBITS-1:0] x5_real = fire ? {x5n_hi[0], x5n_lo[0]} : {CBITS{1'b0}};
    wire signed [CBITS-1:0] x5_imag = fire ? {x5n_hi[1], x5n_lo[1]} : {CBITS{1'b0}};

    assign y_real = y5[CBITS-1 -:OBITS] + y5[(CBITS-1)-OBITS];  // output data with truncation to remove DC spur
    assign y_imag = s5[CBITS-1 -:OBITS] + s5[(CBITS-1)-OBITS];

    always @(posedge clock) begin
        if (clock_en) begin
            counter <= event_now ? 9'd0 : counter + 1'd1;
            req <= event_now;
            fire <= event_now;
            y1 <= y1 + x5_real;
            y2 <= y2 + y1;
            y3 <= y3 + y2;
            y4 <= y4 + y3;
            y5 <= y5 + y4;
            s1 <= s1 + x5_imag;
            s2 <= s2 + s1;
            s3 <= s3 + s2;
            s4 <= s4 + s3;
            s5 <= s5 + s4;
        end else begin
            req <= 1'b0;
        end
    end

    // -------------------------------------------------------------- sequencer
    reg [5:0] step = 6'd0;
    reg       running = 1'b0;
    reg       bank = 1'b1;          // bank holding xs(k) after event k
    reg signed [IBITS-1:0] in_real = 0, in_imag = 0;

    always @(posedge clock) begin
        if (clock_en) begin
            if (event_now) begin
                step <= 6'd0;
                running <= 1'b1;
                bank <= ~bank;
                in_real <= x_real;
                in_imag <= x_imag;
            end else if (running) begin
                step <= step + 6'd1;
                if (step == LAST_STEP) running <= 1'b0;
            end
        end
    end

    // Read side: op o = (step - 4) / 4 covers stage 4 - o / 2, channel o % 2.
    wire [5:0] rstep = step - 6'd4;
    wire [3:0] rop   = rstep[5:2];
    wire [1:0] rph   = rstep[1:0];
    wire [2:0] rstage = 3'd4 - rop[3:1];
    wire [5:0] raddr = {rop[0], rstage, bank ^ rph[0], rph[1]};

    // Process side: data read at step t is in mem_q2 at step t + 2.
    wire [5:0] pstep = step - 6'd6;
    wire [3:0] pop   = pstep[5:2];
    wire [1:0] pph   = pstep[1:0];
    wire [2:0] pstage = 3'd4 - pop[3:1];
    wire       pchan = pop[0];
    wire       processing = running && step >= 6'd6 && step <= LAST_STEP;

    // ------------------------------------------------------------------- RAM
    (* ramstyle = "M9K" *) reg [LO-1:0] comb_mem [0:63];
    reg [LO-1:0] mem_q = 0, mem_q2 = 0;
    reg [LO-1:0] a_reg = 0;
    reg          borrow = 1'b0;

    integer m;
    initial for (m = 0; m < 64; m = m + 1) comb_mem[m] = {LO{1'b0}};

    wire signed [CBITS-1:0] in_sx = (step[1] ? in_imag : in_real);
    wire [LO:0]   diff_lo = {1'b0, a_reg} - {1'b0, mem_q2};
    wire [HI-1:0] diff_hi = a_reg[HI-1:0] - mem_q2[HI-1:0] - borrow;

    reg          wen;
    reg [5:0]    waddr;
    reg [LO-1:0] wdata;
    always @* begin
        wen = 1'b0;
        waddr = 6'd0;
        wdata = {LO{1'b0}};
        if (running && step <= 6'd3) begin
            // New x0 into bank k % 2: I low, I high, Q low, Q high.
            wen = 1'b1;
            waddr = {step[1], 3'd0, bank, step[0]};
            wdata = step[0] ? {{(LO-HI){1'b0}}, in_sx[CBITS-1:LO]} : in_sx[LO-1:0];
        end else if (processing && pph[0] && pstage != 3'd4) begin
            wen = 1'b1;
            waddr = {pchan, pstage + 3'd1, ~bank, pph[1]};
            wdata = pph[1] ? {{(LO-HI){1'b0}}, diff_hi} : diff_lo[LO-1:0];
        end
    end

    always @(posedge clock) begin
        if (clock_en) begin
            mem_q <= comb_mem[raddr];
            mem_q2 <= mem_q;
            if (wen) comb_mem[waddr] <= wdata;
            if (processing) begin
                if (!pph[0]) a_reg <= mem_q2;
                if (pph == 2'd1) borrow <= diff_lo[LO];
                if (pph[0] && pstage == 3'd4) begin
                    if (pph[1]) x5n_hi[pchan] <= diff_hi;
                    else        x5n_lo[pchan] <= diff_lo[LO-1:0];
                end
            end
        end
    end

endmodule
