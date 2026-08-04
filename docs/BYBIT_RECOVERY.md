# Bybit recovery runbook

## Purpose

Recover incomplete monthly Bybit artifacts without allowing one failed matrix job to cancel the remaining months.

## Recovery workflow

The `Recover incomplete Bybit months` workflow runs one month at a time with `fail-fast: false`, a 90-minute job timeout, and up to three bounded attempts per month.

Each successful month uploads an artifact named:

```text
bybit-chunk-<NN>-attempt-<RUN_ATTEMPT>
```

This matches the artifact prefix consumed by both final aggregation workflows.

## HTTP resilience

`sitecustomize.py` installs a process-wide wrapper for requests to `public.bybit.com` only. It:

- preserves caller-supplied headers;
- adds browser-compatible defaults when absent;
- retries HTTP 403, 408, 425, 429, 500, 502, 503, and 504 responses;
- uses bounded exponential backoff with jitter;
- stops after six request attempts.

Requests to other hosts are passed through unchanged.

## Completion sequence

1. Wait for all recovery jobs to finish successfully.
2. Confirm artifacts exist for every required chunk.
3. Run `Aggregate final Bybit history`.
4. Run `Finalize Bybit full history`.
5. Verify the final report has six ready series and no missing, duplicate, off-grid, or invalid OHLC candles.

## Failure handling

A repeated 403 after all retries is treated as non-transient and requires changing the archive source or network path. A runner shutdown or exit code 143 is treated as transient and can be retried through the recovery workflow.
