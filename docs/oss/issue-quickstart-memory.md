# `MIN_MEMORY_NEEDED = 4.3 GB` is below what quickstart actually needs; OpenSearch OOMs on thread stacks with a misleading downstream symptom

## Summary

`datahub docker quickstart`'s preflight check passes at 4.3 GB of Docker
memory, but the six containers it starts idle at **~4.2 GiB combined** on
a freshly loaded instance. A user who allocates the documented minimum
clears the check with essentially no headroom and then hits failures under
normal indexing load.

Separately, when OpenSearch does die, it dies with
`OutOfMemoryError: unable to create native thread` — **not** heap
exhaustion — and the symptom surfaced to the user is a
`ESQueryException: ... Name does not resolve` from GMS, which reads like a
DNS or configuration fault rather than a dead container.

## Environment

| | |
|---|---|
| `acryl-datahub` | 1.6.0.15 |
| DataHub images | `v1.5.0.6` (gms, frontend, actions) |
| OpenSearch image | `opensearchproject/opensearch:2.19.3` |
| Docker Engine | 29.6.2 (Docker Desktop, macOS 15.6.1, arm64) |
| Docker memory allocated | 9.7 GB |
| Docker CPUs | 8 |

## Measured idle usage

`docker stats --no-stream`, quickstart with the `showcase-ecommerce`
datapack loaded (~1050 entities) plus a small custom dataset — i.e. a
realistic evaluation instance, not a production one, and idle at the time
of measurement:

| Container | Memory |
|---|---|
| `datahub-gms` | 1.598 GiB |
| `opensearch` | 1.304 GiB |
| `kafka-broker` | 780 MiB |
| `frontend` | 701 MiB |
| `mysql` | 563 MiB |
| `datahub-actions` | 236 MiB |
| **Total** | **~4.23 GiB** |

That is already above `MIN_MEMORY_NEEDED = 4.3` GB once you account for
GiB/GB units (4.23 GiB ≈ 4.54 GB), before any indexing work, and before
the Docker VM's own overhead.

The constant is here, with a comment suggesting the value was chosen as
"4 GB plus a bit of buffer" rather than measured against the running
stack:

https://github.com/datahub-project/datahub/blob/master/metadata-ingestion/src/datahub/cli/docker_check.py

```python
# Docker seems to under-report memory allocated, so we also need a bit of buffer to account for it.
MIN_MEMORY_NEEDED = 4.3  # GB
MIN_DISK_SPACE_NEEDED = 13  # GB
```

## The failure is thread stacks, not heap

This is the part I think is worth acting on, because raising the heap is
the intuitive fix and it would not help.

The quickstart compose caps OpenSearch's heap at 1 GB:

```yaml
OPENSEARCH_JAVA_OPTS: -Xms768m -Xmx1024m -Dlog4j2.formatMsgNoLookups=true
```

The crash was not heap exhaustion:

```
[warning][os,thread] Failed to start thread "Unknown thread" - pthread_create failed (EAGAIN)
                     for attributes: stacksize: 1024k, guardsize: 4k, detached.
[ERROR][o.o.b.OpenSearchUncaughtExceptionHandler] [search] fatal error in thread
        [opensearch[search][scheduler][T#1]], exiting
java.lang.OutOfMemoryError: unable to create native thread: possibly out of memory
        or process/resource limits reached
        at java.base/java.lang.Thread.start0(Native Method)
        ...
```

The container exited 127. Contributing factors:

- OpenSearch sizes its thread pools from the host CPU count. The container
  sees `nproc` = 8 here.
- Thread count observed in the container: **3042** live threads
  (`ls /proc/*/task | wc -l`), and the log shows pool threads numbered
  into the 700s for a single pool, i.e. significant churn.
- The JVM's default thread stack on this platform is **1024k** (visible in
  the log line above). Several thousand threads at ~1 MB of committed
  stack each is another multi-GB of memory **outside** the heap.

`ulimit -u` inside the container is `unlimited` and the host's
`kernel.threads-max` is 79473, so this is memory pressure on thread stack
allocation rather than a hard thread-count ceiling.

Net effect: OpenSearch's real memory footprint scales with the host's core
count in a way neither `-Xmx` nor the documented minimum reflects. On an
8-core machine it OOM'd even at a 9.7 GB Docker allocation.

## The downstream symptom is misleading

Once OpenSearch is gone, GMS keeps serving. Any search-backed GraphQL
field then fails with:

```
com.datahub.util.exception.ESQueryException: Search query failed:.
  Root cause: Search query failed:. search: Name does not resolve
```

"Name does not resolve" reads as a DNS/hostname/configuration problem —
the actual cause is that the `search` host is a container that is no
longer running. Entity-by-URN reads keep working, so the instance appears
partially healthy, which makes it harder still to attribute. It cost me a
while to trace this back to a dead container rather than a client config
error.

Recovery is simply `docker start datahub-opensearch-1`; data survives in
the `osdata` volume.

## Suggested fixes

Either would help; they are independent.

**1. Raise the preflight minimum, and measure it against a loaded
instance.** The current value doesn't cover the stack it starts. Something
in the 8 GB range matches what the stack actually needs with room for
indexing. If the intent is to keep the barrier to entry low, splitting the
check into a hard minimum plus a warned-but-allowed "recommended" band
would preserve that while telling the user the truth.

**2. Stop OpenSearch's thread footprint from scaling with host cores.**
Two small compose changes would bound it:

```yaml
OPENSEARCH_JAVA_OPTS: -Xms768m -Xmx1024m -Xss256k -Dlog4j2.formatMsgNoLookups=true
# and/or
node.processors: 2
```

`-Xss256k` cuts committed stack per thread fourfold; `node.processors`
caps the pool sizing that drives the thread count in the first place.
Neither is appropriate for a production deployment, but quickstart is
explicitly a single-node evaluation profile where bounding resource use
matters more than search throughput.

**3. (Smaller) Make the dead-container case diagnosable.** If GMS can
distinguish "search host unreachable" from "query failed", surfacing that
in the error — or having `datahub docker check` flag an exited container
among an otherwise healthy set — would save the next person the same hunt.

## Notes

Happy to open a PR for either fix if you tell me which direction you'd
prefer. I don't have a reliable reproduction of the OOM itself — it
happened once under sustained development use rather than from a clean
script — so I've kept this to what I measured directly rather than
speculating about the exact trigger.
