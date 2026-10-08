# Measured workload report

Core and CLI times are scenario processing, in milliseconds. RSS includes full canonical history.
macOS RSS is provisional; authoritative memory requires Linux. Expected reachability failures count as completed work.

| Cell | R/L/P | Events/assertions/destinations | Status | Core median [min,max] ms | CLI median [min,max] ms | Peak RSS median MiB |
| --- | --- | --- | --- | --- | --- | --- |
| chain-16 | 16/15/2 | 8/1/1 | complete | 0.134 [0.133,0.137] | 5.602 [5.512,5.641] | 3.77 |
| chain-64 | 64/63/2 | 8/1/1 | complete | 1.137 [1.112,1.270] | 13.463 [12.980,13.695] | 6.48 |
| chain-256 | 256/255/2 | 8/1/1 | complete | 16.670 [15.578,17.672] | 56.970 [54.968,60.219] | 17.62 |
| chain-1024 | 1024/1023/2 | 8/1/1 | budget_skipped | — | — | — |
| ring-16 | 16/16/2 | 8/1/1 | complete | 0.148 [0.136,0.155] | 5.757 [5.568,5.947] | 3.77 |
| grid-16 | 16/23/2 | 8/1/1 | complete | 0.224 [0.218,0.238] | 6.287 [6.165,6.323] | 3.97 |
| diamond-width-2 | 16/19/2 | 8/1/1 | complete | 0.185 [0.181,0.188] | 5.900 [5.737,6.392] | 3.94 |
| diamond-width-4 | 16/21/2 | 8/1/1 | complete | 0.207 [0.203,0.229] | 5.990 [5.883,6.197] | 3.97 |
| sparse-16 | 16/30/2 | 8/1/1 | complete | 0.226 [0.215,0.230] | 5.922 [5.815,6.094] | 3.92 |
| sparse-denser-16 | 16/45/2 | 8/1/1 | complete | 0.290 [0.285,0.459] | 7.071 [6.870,20.730] | 4.22 |
| ring-prefix-density-1 | 16/16/16 | 8/1/1 | complete | 0.262 [0.256,0.281] | 23.243 [22.618,23.479] | 10.28 |
| ring-prefix-density-2 | 16/16/32 | 8/2/2 | complete | 0.325 [0.309,0.327] | 43.316 [42.770,45.400] | 17.80 |
| ring-all-assertions | 16/16/16 | 8/256/16 | complete | 0.563 [0.546,0.594] | 33.486 [33.064,33.781] | 15.23 |
| ring-long-trace | 16/16/2 | 32/1/1 | complete | 0.431 [0.418,0.448] | 12.865 [12.580,13.080] | 6.27 |
| ring-64 | 64/64/64 | 8/1/1 | complete | 3.072 [2.989,3.095] | 339.457 [336.019,341.623] | 103.19 |
| ring-256-dense-probe | 256/256/512 | 8/2/2 | budget_skipped | — | — | — |

Actual counters (baseline / snapshot range; logical references include shared sets):

| Cell | Route entries | Next-hop references | Applied/no-op events | Assertion evaluations | Destination analyses |
| --- | --- | --- | --- | --- | --- |
| chain-16 | 32 / [15, 32] | 30 / [14, 30] | 6/2 | 9 | 9 |
| chain-64 | 128 / [63, 128] | 126 / [62, 126] | 6/2 | 9 | 9 |
| chain-256 | 512 / [255, 512] | 510 / [254, 510] | 6/2 | 9 | 9 |
| ring-16 | 32 / [15, 32] | 30 / [14, 30] | 6/2 | 9 | 9 |
| grid-16 | 32 / [15, 32] | 46 / [21, 46] | 6/2 | 9 | 9 |
| diamond-width-2 | 32 / [15, 32] | 38 / [18, 38] | 6/2 | 9 | 9 |
| diamond-width-4 | 32 / [15, 32] | 42 / [20, 42] | 6/2 | 9 | 9 |
| sparse-16 | 32 / [15, 32] | 38 / [18, 38] | 6/2 | 9 | 9 |
| sparse-denser-16 | 32 / [15, 32] | 60 / [25, 60] | 6/2 | 9 | 9 |
| ring-prefix-density-1 | 256 / [225, 256] | 240 / [210, 240] | 6/2 | 9 | 9 |
| ring-prefix-density-2 | 512 / [450, 512] | 480 / [420, 480] | 6/2 | 18 | 18 |
| ring-all-assertions | 256 / [225, 256] | 240 / [210, 240] | 6/2 | 2304 | 144 |
| ring-long-trace | 32 / [15, 32] | 30 / [14, 30] | 24/8 | 33 | 33 |
| ring-64 | 4096 / [3969, 4096] | 4032 / [3906, 4032] | 6/2 | 9 | 9 |

chain-1024: spf_work_units=28293120 exceeds 10000000

ring-256-dense-probe: retained_route_upper_bound=1179648 exceeds 100000; output_bytes_estimate=1057277952 exceeds 50331648; rss_bytes_estimate=4296220672 exceeds 805306368
