# Design decision

Fresh requalification data is acquired from the canonical public Bybit REST endpoint on a hosted GitHub job and transported to the physical runner as a digest-pinned snapshot. This preserves the approved Bybit REST provenance contract while avoiding the physical runner's regional REST reachability failure. The physical runner independently verifies freshness and lineage and performs the Strategy Factory requalification itself.
