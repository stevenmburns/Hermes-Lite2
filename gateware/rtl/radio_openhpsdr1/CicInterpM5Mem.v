// CicInterpM5 with its comb state in one block RAM.
//
// Same ports, parameters and output, bit for bit, as CicInterpM5.v. The five
// integrators per channel still run on every enabled clock in registers. The
// combs run once every RRRR enabled clocks, so their state moves into a
// 32 x CW RAM (one M9K) and one subtractor computes them serially.
//
// CicInterpM5's comb is pipelined: after comb event k,
//   x0(k) = input sampled at event k
//   xs(k) = x(s-1)(k-1) - x(s-1)(k-2)      s = 1..5
// and x5(k) feeds the first integrator on the next enabled clock. Every xs(k)
// for s >= 1 depends only on values from earlier events, so this version
// computes them in the gap after event k-1 and keeps x5(k) ready in x5n.
//
// Each stage grows the IBITS-bit input by at most one bit, so every xs fits in
// CW = IBITS + 5 signed bits. Computing modulo 2^CW and sign-extending x5 gives
// the same integrator input as CicInterpM5's CBITS-wide combs.
//
// RAM address {channel, stage[2:0], bank}: xs(k) is stored in bank k % 2.
//   event edge    writes the new I x0 to the bank for event k, and keeps Q
//   step 0        writes the new Q x0
//   steps 1..20   issue 20 reads, 2 per (stage, channel) for stages 4 down to
//                 0: A = xs(k), then B = xs(k-1)
//   steps 3..22   get each read back two steps later and write A - B to
//                 x(s+1) in the other bank, or to x5n for stage 4
// Stages run high to low, so each write replaces a value its own stage has
// already read. The sequence ends at step 22, so RRRR must be at least 24
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
    localparam CW = IBITS + 5;          // comb width: one bit of growth per stage
    localparam LAST_STEP = 22;

    reg [8:0] counter = 9'd0;
    wire event_now = (counter == RRRR - 1);

    // ------------------------------------------------------------ integrators
    reg signed [CBITS-1:0] y1 = 0, y2 = 0, y3 = 0, y4 = 0, y5 = 0;
    reg signed [CBITS-1:0] s1 = 0, s2 = 0, s3 = 0, s4 = 0, s5 = 0;
    reg signed [CW-1:0] x5n_real = 0, x5n_imag = 0;
    reg fire = 1'b0;    // the enabled clock after an event, when x5 is nonzero

    initial req = 1'b0;

    // Explicit sign extension: an unsigned zero in a ?: would zero-extend x5n.
    wire signed [CBITS-1:0] x5_real = fire ? {{(CBITS-CW){x5n_real[CW-1]}}, x5n_real} : {CBITS{1'b0}};
    wire signed [CBITS-1:0] x5_imag = fire ? {{(CBITS-CW){x5n_imag[CW-1]}}, x5n_imag} : {CBITS{1'b0}};

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
    reg [4:0] step = 5'd0;
    reg       running = 1'b0;
    reg       bank = 1'b1;          // bank holding xs(k) after event k
    reg signed [IBITS-1:0] in_imag = 0;

    always @(posedge clock) begin
        if (clock_en) begin
            if (event_now) begin
                step <= 5'd0;
                running <= 1'b1;
                bank <= ~bank;
                in_imag <= x_imag;
            end else if (running) begin
                step <= step + 5'd1;
                if (step == LAST_STEP) running <= 1'b0;
            end
        end
    end

    // Read side: op o = (step - 1) / 2 covers stage 4 - o / 2, channel o % 2.
    wire [4:0] rstep  = step - 5'd1;
    wire [3:0] rop    = rstep[4:1];
    wire [2:0] rstage = 3'd4 - rop[3:1];
    wire [4:0] raddr  = {rop[0], rstage, bank ^ rstep[0]};

    // Process side: data read at step t is in mem_q2 at step t + 2.
    wire [4:0] pstep  = step - 5'd3;
    wire [3:0] pop    = pstep[4:1];
    wire [2:0] pstage = 3'd4 - pop[3:1];
    wire       pchan  = pop[0];
    wire       processing = running && step >= 5'd3 && step <= LAST_STEP;

    // ------------------------------------------------------------------- RAM
    (* ramstyle = "M9K" *) reg [CW-1:0] comb_mem [0:31];
    reg [CW-1:0] mem_q = 0, mem_q2 = 0;
    reg [CW-1:0] a_reg = 0;

    integer m;
    initial for (m = 0; m < 32; m = m + 1) comb_mem[m] = {CW{1'b0}};

    wire signed [CW-1:0] in_real_sx = x_real;
    wire signed [CW-1:0] in_imag_sx = in_imag;
    wire [CW-1:0] diff = a_reg - mem_q2;

    reg          wen;
    reg [4:0]    waddr;
    reg [CW-1:0] wdata;
    always @* begin
        wen = 1'b0;
        waddr = 5'd0;
        wdata = {CW{1'b0}};
        if (event_now) begin
            // The bank toggles on this edge, so x0(k) for I goes to ~bank.
            wen = 1'b1;
            waddr = {1'b0, 3'd0, ~bank};
            wdata = in_real_sx;
        end else if (running && step == 5'd0) begin
            wen = 1'b1;
            waddr = {1'b1, 3'd0, bank};
            wdata = in_imag_sx;
        end else if (processing && pstep[0] && pstage != 3'd4) begin
            wen = 1'b1;
            waddr = {pchan, pstage + 3'd1, ~bank};
            wdata = diff;
        end
    end

    always @(posedge clock) begin
        if (clock_en) begin
            mem_q <= comb_mem[raddr];
            mem_q2 <= mem_q;
            if (wen) comb_mem[waddr] <= wdata;
            if (processing) begin
                if (!pstep[0]) a_reg <= mem_q2;
                if (pstep[0] && pstage == 3'd4) begin
                    if (pchan) x5n_imag <= diff;
                    else       x5n_real <= diff;
                end
            end
        end
    end

endmodule
