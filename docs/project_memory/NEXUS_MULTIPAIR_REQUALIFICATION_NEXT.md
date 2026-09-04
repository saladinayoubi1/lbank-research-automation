# Next integration step

After exact-head CI accepts the fresh runtime snapshot contract, wire it into a dedicated proof workflow with this order:

1. hosted wheelhouse + immutable historical Bybit archive acquisition;
2. physical historical Discovery on `nexus-bybit-network`;
3. hosted fresh canonical Bybit REST snapshot acquisition at exact source SHA;
4. physical digest-pinned restore, freshness verification, canonical re-bind and independent requalification;
5. compact hosted proof persistence.

Fresh acquisition must occur after Discovery so the 15-minute evidence does not age out while historical Discovery runs.
