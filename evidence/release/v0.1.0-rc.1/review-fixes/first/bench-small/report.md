# Measured workload report

Core and CLI times are scenario processing, in milliseconds. RSS includes full canonical history.
macOS RSS is provisional; authoritative memory requires Linux. Expected reachability failures count as completed work.

| Cell | R/L/P | Events/assertions/destinations | Status | Core median [min,max] ms | CLI median [min,max] ms | Peak RSS median MiB |
| --- | --- | --- | --- | --- | --- | --- |
| sparse-small-16 | 16/30/2 | 8/1/1 | complete | 0.234 [0.219,0.235] | 6.037 [5.957,6.754] | 3.98 |

Actual counters (baseline / snapshot range; logical references include shared sets):

| Cell | Route entries | Next-hop references | Applied/no-op events | Assertion evaluations | Destination analyses |
| --- | --- | --- | --- | --- | --- |
| sparse-small-16 | 32 / [15, 32] | 38 / [18, 38] | 6/2 | 9 | 9 |
